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
PORT = int(os.environ.get("ADHOC_PORT", "5004"))
IP_PREFIX = os.environ.get("ADHOC_NET", "192.168.99")
# Use subnet broadcast for streaming — multicast is unreliable in IBSS/ad-hoc mode
STREAM_ADDR = f"{IP_PREFIX}.255"

logger = logging.getLogger(__name__)


class Streamer:
    def __init__(
        self,
        song_change_callback: Optional[Callable[[str], None]] = None,
        on_eof_callback: Optional[Callable[[], None]] = None,
    ):
        self.proc: Optional[subprocess.Popen] = None
        self.lock = threading.RLock()
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
        start = time.time()
        with self.lock:
            proc = self.proc
        if proc:
            _, stderr_data = proc.communicate()
            elapsed = time.time() - start
            ended_current = False
            with self.lock:
                if self.proc is proc:
                    self.proc = None
                    ended_current = True
            if stderr_data:
                tail = stderr_data.decode("utf-8", errors="replace").strip()[-600:]
                if elapsed < 5:
                    logger.error("ffmpeg terminó rápido (%.1fs). Stderr: %s", elapsed, tail)
                else:
                    logger.debug("ffmpeg stderr (últimas líneas): %s", tail)
            # Solo notificar EOF si este proceso seguía siendo el activo.
            # Si terminó porque stop() lo reemplazó, no debemos disparar otra
            # selección/reinicio fantasma.
            if ended_current and self.on_eof:
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
                f"udp://{STREAM_ADDR}:{PORT}?broadcast=1&pkt_size=1316"
            ]
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
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
        logger.info("Iniciando cliente de stream en UDP broadcast :%d", PORT)
        with self.lock:
            self.stop()
            self.current_song = f"Stream UDP broadcast :{PORT}"
            if self.callback:
                self.callback(self.current_song)

            # ffplay recibe mejor UDP broadcast en IBSS que mpv. Usamos @:PORT
            # para bind explícito local, con buffers grandes para evitar cortes.
            player = os.environ.get("ADHOC_PLAYER", "ffplay")
            ff_url = f"udp://@:{PORT}?fifo_size=1000000&overrun_nonfatal=1"
            mpv_url = f"udp://0.0.0.0:{PORT}"
            if player == "mpv" and subprocess.call(["which", "mpv"], stdout=subprocess.DEVNULL) == 0:
                cmd = [
                    "mpv", "--no-cache", "--demuxer-readahead-secs=0",
                    "--cache-secs=0", "--untimed", "--no-video", mpv_url,
                ]
            else:
                cmd = [
                    "ffplay", "-hide_banner", "-loglevel", "warning",
                    "-fflags", "nobuffer", "-flags", "low_delay",
                    "-probesize", "32", "-analyzeduration", "0",
                    "-nodisp", "-i", ff_url,
                ]
            logger.info("Comando cliente stream: %s", " ".join(cmd))
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
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
        Escucha el puerto de stream durante `timeout` segundos.
        Devuelve True si detecta paquetes UDP (otro Master activo).
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            sock.bind(("0.0.0.0", PORT))
            sock.settimeout(timeout)
            logger.debug("Sniffing stream UDP :%d por %.1fs...", PORT, timeout)
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
            logger.error("Error en sniff_stream: %s", e)
            return False
