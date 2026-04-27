#!/usr/bin/env python3
"""
node-daemon.py — Orquestador principal del nodo AD-HOC streaming.

Hilos:
- Heartbeat emisor (con flag is_master)
- Heartbeat receptor (AdhocManager)
- Cleanup de peers
- Resolución de conflictos IP (solo Master)
- Persistencia de estado
- Reescaneo de red y migración de celda
- Decisión de Master + sniffing anti-split-brain
- Control de streaming con pausa en transiciones
- API web (Flask)

Arquitectura streaming:
- Todos los nodos sirven sus canciones locales vía HTTP (:8080/music/).
- El Master elige canciones de TODA la red (locales + peers).
- Sniffing previo al stream para evitar colisión de Masters.
- Si la canción cambia por transición de Master, los nodos entran en PAUSA
  hasta que el usuario presione PLAY (evita cambios abruptos).
- Cualquier nodo puede solicitar canción desde su panel web (song_request broadcast).
"""

import os
import sys
import time
import threading
import random
import logging
import logging.handlers
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from network.adhoc_manager import AdhocManager
from streaming.streamer import Streamer
from monitoring.monitor import build_status
from web import app as webapp
from node import state as node_state

NODE_ID = os.environ.get("NODE_ID", "unknown")
MASTER_PICK_INTERVAL = 0
REJOIN_INTERVAL = 60
REPO_ROOT = "/opt/adhoc-node/repo"


def setup_logging():
    log_dir = Path("/opt/adhoc-node/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "daemon.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


class NodeDaemon:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.net = AdhocManager(
            extra_heartbeat_fn=self._extra_heartbeat,
            on_song_request_fn=self._on_song_request,
        )
        self.streamer = Streamer(
            song_change_callback=self._on_song_change,
            on_eof_callback=self._on_stream_eof,
        )
        self.is_master = False
        self.forced_master = False
        self.forced_song: str | None = None
        self.last_pick_time = 0
        self.current_song = "Ninguna"
        self.previous_song = "Ninguna"
        self.paused = False
        self.lock = threading.Lock()
        self.client_restart_pending = False

        webapp._daemon_state["status_fn"] = self.get_status
        webapp._daemon_state["force_song_fn"] = self.force_song
        webapp._daemon_state["force_master_fn"] = self.force_master
        webapp._daemon_state["toggle_pause_fn"] = self.toggle_pause

    def _extra_heartbeat(self) -> dict:
        with self.lock:
            master = self.is_master
        return {
            "songs": [s.name for s in self.streamer._songs()],
            "is_master": master,
        }

    def _on_song_request(self, song_name: str):
        with self.lock:
            if self.is_master:
                self.logger.info("Master recibió solicitud de canción: %s", song_name)
                self.forced_song = song_name

    def _on_song_change(self, name: str):
        with self.lock:
            self.current_song = name
        self.logger.info("Ahora sonando: %s", name)

    def _on_stream_eof(self):
        with self.lock:
            if self.is_master:
                self.logger.info("Stream master terminó, eligiendo siguiente...")
                self._pick_and_stream()
            else:
                self.logger.info("Cliente stream terminó, marcando reinicio...")
                self.client_restart_pending = True

    def _resolve_song(self, song_name: str):
        for s in self.streamer._songs():
            if s.name == song_name:
                return (s, None)
        peers = self.net.get_peers_snapshot()
        for nid, info in peers.items():
            if song_name in info.get("songs", []):
                peer_ip = info.get("ip")
                if peer_ip and peer_ip != "0.0.0.0":
                    return (None, peer_ip)
        return (None, None)

    def _another_master_with_higher_score(self) -> bool:
        """Detecta si hay otro Master conocido con mejor score que nosotros."""
        my_score = self.net._my_score()
        peers = self.net.get_peers_snapshot()
        for nid, info in peers.items():
            if info.get("is_master") and info.get("score", 0) > my_score:
                return True
        return False

    def force_song(self, song_name: str) -> bool:
        self.logger.info("Solicitando canción vía broadcast: %s", song_name)
        self.net.send_song_request(song_name)
        with self.lock:
            if self.is_master:
                self.forced_song = song_name
        return True

    def force_master(self):
        with self.lock:
            self.forced_master = True
            self.is_master = True
        self.logger.info("Master forzado vía API")

    def toggle_pause(self) -> bool:
        with self.lock:
            self.paused = not self.paused
            new_state = self.paused
        self.logger.info("Pausa toggled: %s", new_state)
        return new_state

    def _get_all_network_songs(self) -> list:
        """Devuelve lista de (song_name, source_node_id, is_local) para toda la red."""
        songs = []
        seen = set()
        for s in self.streamer._songs():
            if s.name not in seen:
                songs.append((s.name, NODE_ID, True))
                seen.add(s.name)
        peers = self.net.get_peers_snapshot()
        for nid, info in peers.items():
            for song_name in info.get("songs", []):
                if song_name not in seen:
                    songs.append((song_name, nid, False))
                    seen.add(song_name)
        return songs

    def get_status(self):
        with self.lock:
            master = self.is_master
            song = self.current_song
            paused = self.paused
        peers = self.net.get_peers_snapshot()
        data = build_status(master, song, peers)
        data["paused"] = paused
        data["all_network_songs"] = self._get_all_network_songs()
        return data

    def _pick_and_stream(self):
        with self.lock:
            forced = self.forced_song
            self.forced_song = None

        if forced:
            # Si ya está sonando, no reiniciar
            with self.lock:
                if forced == self.current_song and self.streamer.is_running():
                    self.logger.info("Canción '%s' ya en streaming. Ignorando solicitud.", forced)
                    return
            local_path, peer_ip = self._resolve_song(forced)
            if local_path:
                self.logger.info("Master forzando canción local: %s", forced)
                self.streamer.start_server(local_path)
                return
            elif peer_ip:
                url = f"http://{peer_ip}:8080/music/{forced}"
                self.logger.info("Master forzando canción remota: %s desde %s", forced, peer_ip)
                self.streamer.start_server_from_url(url, forced)
                return
            else:
                self.logger.warning("Canción forzada no encontrada en red: %s", forced)

        all_songs = []
        for s in self.streamer._songs():
            all_songs.append((s.name, s, None))
        peers = self.net.get_peers_snapshot()
        for nid, info in peers.items():
            peer_ip = info.get("ip")
            if peer_ip and peer_ip != "0.0.0.0":
                for song_name in info.get("songs", []):
                    all_songs.append((song_name, None, peer_ip))

        if not all_songs:
            self.logger.warning("No hay canciones disponibles en la red")
            return

        choice = random.choice(all_songs)
        song_name, local_path, peer_ip = choice

        if local_path:
            self.logger.info("Master elige aleatoriamente local: %s", song_name)
            self.streamer.start_server(local_path)
        else:
            url = f"http://{peer_ip}:8080/music/{song_name}"
            self.logger.info("Master elige aleatoriamente remota: %s desde %s", song_name, peer_ip)
            self.streamer.start_server_from_url(url, song_name)

    def _heartbeat_loop(self):
        while True:
            try:
                with self.lock:
                    master = self.is_master
                self.net.send_heartbeat(is_master=master)
            except Exception:
                self.logger.exception("Error enviando heartbeat")
            time.sleep(3)

    def _cleanup_loop(self):
        while True:
            time.sleep(10)
            try:
                self.net.cleanup_peers()
            except Exception:
                self.logger.exception("Error en cleanup de peers")

    def _ip_conflict_loop(self):
        while True:
            time.sleep(10)
            if not self.is_master:
                continue
            try:
                conflicts = self.net.detect_ip_conflicts()
                for ip, nid_a, nid_b in conflicts:
                    peers = self.net.get_peers_snapshot()
                    score_a = peers.get(nid_a, {}).get("score", 0)
                    score_b = peers.get(nid_b, {}).get("score", 0)
                    target = nid_b if score_b <= score_a else nid_a
                    new_ip = self.net.pick_free_ip()
                    self.logger.info(
                        "Conflicto IP %s entre %s(%s) y %s(%s). Reasignando %s -> %s",
                        ip, nid_a, score_a, nid_b, score_b, target, new_ip,
                    )
                    self.net.send_ip_reassign(target, new_ip)
            except Exception:
                self.logger.exception("Error en resolución de conflictos IP")

    def _state_persist_loop(self):
        while True:
            time.sleep(5)
            try:
                with self.lock:
                    cell_id = ""
                    try:
                        with open("/tmp/adhoc/cell_id") as f:
                            cell_id = f.read().strip()
                    except Exception:
                        pass
                    payload = {
                        "cell_id": cell_id,
                        "is_master": self.is_master,
                        "current_song": self.current_song,
                        "node_id": NODE_ID,
                    }
                if node_state.save(payload):
                    self.logger.debug("Estado persistido: cell=%s master=%s song=%s",
                                      cell_id, payload["is_master"], payload["current_song"])
            except Exception:
                self.logger.exception("Error persistiendo estado")

    def _rejoin_loop(self):
        script = f"{REPO_ROOT}/scripts/network-rejoin.sh"
        while True:
            time.sleep(REJOIN_INTERVAL)
            try:
                result = subprocess.run(
                    ["bash", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    self.logger.info("Rejoin: %s", result.stdout.strip())
                elif result.returncode != 0 and result.stderr:
                    self.logger.warning("Rejoin stderr: %s", result.stderr.strip())
            except subprocess.TimeoutExpired:
                self.logger.warning("Rejoin script timeout")
            except Exception:
                self.logger.exception("Error en rejoin loop")

    def _master_logic(self):
        while True:
            time.sleep(2)
            try:
                with self.lock:
                    forced_master = self.forced_master
                    client_pending = self.client_restart_pending
                    self.client_restart_pending = False

                # Detectar otro Master con mejor score vía heartbeats
                if self._another_master_with_higher_score():
                    with self.lock:
                        if self.is_master:
                            self.logger.warning("Otro Master con mejor score detectado. Rindiendo...")
                            self.is_master = False
                            self.streamer.stop()
                            self.client_restart_pending = True
                            continue

                # Actualizar estado de master
                master_now = forced_master or self.net.am_i_master()
                with self.lock:
                    became_master = master_now and not self.is_master
                    lost_master = not master_now and self.is_master
                    self.is_master = master_now

                if became_master:
                    self.logger.info("Este nodo es ahora MASTER")
                    # Sniffing previo: verificar que nadie más está streameando
                    if Streamer.sniff_multicast(timeout=2.0):
                        self.logger.warning("Multicast ocupado. Posible otro Master activo.")
                        if self._another_master_with_higher_score():
                            self.logger.info("Rindiendo ante Master con mejor score.")
                            with self.lock:
                                self.is_master = False
                                self.client_restart_pending = True
                            continue
                        else:
                            self.logger.info("No hay Master con mejor score confirmado. Tomando control.")
                    self.streamer.stop()
                    self._pick_and_stream()
                    continue

                if lost_master:
                    self.logger.info("Dejamos de ser master, pasando a cliente")
                    with self.lock:
                        self.previous_song = self.current_song
                    self.streamer.stop()
                    self.client_restart_pending = True
                    continue

                if self.is_master:
                    if not self.streamer.is_running():
                        self._pick_and_stream()
                else:
                    # Cliente: si hay pending y NO estamos pausados, reiniciar
                    with self.lock:
                        paused = self.paused
                    if paused:
                        if client_pending:
                            self.logger.info("Cliente en PAUSA. Ignorando reinicio de stream.")
                        continue
                    if client_pending or not self.streamer.is_running():
                        self.logger.info("Reiniciando receptor de stream...")
                        self.streamer.start_client()
            except Exception:
                self.logger.exception("Error en master logic loop")

    def run(self):
        self.logger.info("Nodo %s iniciando daemon...", NODE_ID)
        self.net.start()

        t_hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t_clean = threading.Thread(target=self._cleanup_loop, daemon=True)
        t_ipconf = threading.Thread(target=self._ip_conflict_loop, daemon=True)
        t_state = threading.Thread(target=self._state_persist_loop, daemon=True)
        t_rejoin = threading.Thread(target=self._rejoin_loop, daemon=True)
        t_master = threading.Thread(target=self._master_logic, daemon=True)
        t_web = threading.Thread(
            target=lambda: webapp.run_web(host="0.0.0.0", port=8080), daemon=True
        )

        t_hb.start()
        t_clean.start()
        t_ipconf.start()
        t_state.start()
        t_rejoin.start()
        t_master.start()
        t_web.start()

        while True:
            time.sleep(1)


if __name__ == "__main__":
    setup_logging()
    NodeDaemon().run()
