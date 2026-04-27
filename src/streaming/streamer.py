#!/usr/bin/env python3
"""
streamer.py — Control de ffmpeg servidor (Master) y reproductor cliente.
Detecta EOF automáticamente y notifica para reinicio.
"""

import os
import random
import socket
import struct
import subprocess
import threading
import signal
import time
import logging
from pathlib import Path
from typing import List, Optional, Callable

MUSIC_DIR = Path(os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music"))
MULTI_ADDR = os.environ.get("ADHOC_MULTI", "239.255.42.42")
PORT = int(os.environ.get("ADHOC_PORT", "5004"))

logger = logging.getLogger(__name__)


class Streamer:
    def __init__(
        self,
        song_change_callback: Optional[Callable[[str], None]] = None,
        on_eof_callback: Optional[Callable[[], None]] = None,
    ):
        self.proc: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.current_song = "Ninguna"
        self.callback = song_change_callback
        self.on_eof = on_eof_callback

    def _songs(self) -> List[Path]:
        exts = {".mp3", ".ogg", ".flac", ".wav", ".m4a", ".aac"}
        if not MUSIC_DIR.exists():
            return []
        return sorted([f for f in MUSIC_DIR.iterdir() if f.suffix.lower() in exts])

    def pick_random_song(self) -> Optional[Path]:
        songs = self._songs()
        return random.choice(songs) if songs else None

    def _watchdog(self):
        """Espera a que el proceso termine y notifica EOF."""
        proc = None
        with self.lock:
            proc = self.proc
        if proc:
            proc.wait()
            with self.lock:
                if self.proc is proc:
                    self.proc = None
            if self.on_eof:
                self.on_eof()

    def _start_server_common(self, source: str, song_name: str):
        """Lógica común para iniciar ffmpeg como servidor relay."""
        with self.lock:
            self.stop()
            self.current_song = song_name
            if self.callback:
                self.callback(song_name)
            cmd = [
                "ffmpeg", "-re", "-i", source,
                "-c:a", "libmp3lame", "-b:a", "192k",
                "-f", "mpegts",
                f"udp://{MULTI_ADDR}:{PORT}?ttl=1&pkt_size=1316"
            ]
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            t = threading.Thread(target=self._watchdog, daemon=True)
            t.start()

    def start_server(self, song_path: Path):
        logger.info("Iniciando servidor de stream local: %s", song_path.name)
        self._start_server_common(str(song_path), song_path.name)

    def start_server_from_url(self, url: str, song_name: str):
        """El Master descarga canción de peer vía HTTP y la retransmite por multicast."""
        logger.info("Iniciando servidor relay desde %s: %s", url, song_name)
        self._start_server_common(url, song_name)

    def start_client(self):
        logger.info("Iniciando cliente de stream en %s:%d", MULTI_ADDR, PORT)
        with self.lock:
            self.stop()
            self.current_song = f"Stream multicast {MULTI_ADDR}:{PORT}"
            if self.callback:
                self.callback(self.current_song)

            player = os.environ.get("ADHOC_PLAYER", "mpv")
            url = f"udp://{MULTI_ADDR}:{PORT}"
            if subprocess.call(["which", player], stdout=subprocess.DEVNULL) == 0:
                # Low-latency flags para mpv
                cmd = [
                    player, "--no-cache", "--demuxer-readahead-secs=0",
                    "--cache-secs=0", "--no-video", url,
                ]
            else:
                cmd = [
                    "ffplay", "-fflags", "+nobuffer", "-flags", "low_delay",
                    "-nodisp", "-autoexit", url,
                ]
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            t = threading.Thread(target=self._watchdog, daemon=True)
            t.start()

    def stop(self):
        with self.lock:
            if self.proc:
                logger.debug("Deteniendo proceso de stream (PID %s)", self.proc.pid)
                try:
                    self.proc.send_signal(signal.SIGTERM)
                    self.proc.wait(timeout=2)
                except Exception:
                    self.proc.kill()
                self.proc = None

    def is_running(self) -> bool:
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def sniff_multicast(timeout: float = 2.0) -> bool:
        """
        Escucha el puerto multicast durante `timeout` segundos.
        Devuelve True si detecta paquetes (otro Master activo).
        Se debe llamar ANTES de iniciar el propio stream.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            sock.bind(("0.0.0.0", PORT))

            mreq = struct.pack("4sl", socket.inet_aton(MULTI_ADDR), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            sock.settimeout(timeout)
            logger.debug("Sniffing multicast %s:%d por %.1fs...", MULTI_ADDR, PORT, timeout)
            try:
                data, addr = sock.recvfrom(2048)
                if data:
                    logger.warning("Sniffing detectó stream activo desde %s (%d bytes)", addr[0], len(data))
                    sock.close()
                    return True
            except socket.timeout:
                pass
            sock.close()
            return False
        except Exception as e:
            logger.error("Error en sniff_multicast: %s", e)
            return False
