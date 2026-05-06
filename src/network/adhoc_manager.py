#!/usr/bin/env python3
"""
adhoc_manager.py — Descubrimiento de nodos, heartbeats UDP, elección de Master y DHCP ligero.
"""

import os
import json
import socket
import struct
import threading
import time
import subprocess
import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


def _detect_iface() -> str:
    configured = os.environ.get("ADHOC_IFACE", "")
    if configured and os.path.exists(f"/sys/class/net/{configured}"):
        return configured
    try:
        import pathlib
        for p in pathlib.Path("/sys/class/net").iterdir():
            if (p / "wireless").exists():
                return p.name
    except Exception:
        pass
    return configured or "wlan0"


IFACE = _detect_iface()
MULTI_ADDR = os.environ.get("ADHOC_MULTI", "239.255.42.42")
PORT = int(os.environ.get("ADHOC_PORT", "5004"))
HEARTBEAT_PORT = PORT + 1
# Un peer se considera desconectado si no manda heartbeats en este tiempo.
# Los heartbeats salen cada 3s; 9s mantiene la UI fresca sin nodos fantasma.
PEER_TIMEOUT = float(os.environ.get("ADHOC_PEER_TIMEOUT", "9"))
IP_PREFIX = os.environ.get("ADHOC_NET", "192.168.99")
BROADCAST_ADDR = f"{IP_PREFIX}.255"

NODE_ID = os.environ.get("NODE_ID", "unknown")


class AdhocManager:
    def __init__(
        self,
        extra_heartbeat_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        on_song_request_fn: Optional[Callable[[str], None]] = None,
        port: Optional[int] = None,
    ):
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.extra_heartbeat_fn = extra_heartbeat_fn
        self.on_song_request_fn = on_song_request_fn
        self.port = port if port is not None else HEARTBEAT_PORT
        self.sock: Optional[socket.socket] = None
        self._start_time = time.time()
        self._bind_socket()

    def _bind_socket(self):
        """Crea y bindea el socket UDP. Reintenta si el puerto está ocupado."""
        for attempt in range(5):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
                sock.bind(("0.0.0.0", self.port))
                try:
                    mreq = struct.pack("4sl", socket.inet_aton(MULTI_ADDR), socket.INADDR_ANY)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                except OSError as e:
                    logger.warning("Multicast join falló (no fatal): %s", e)
                self.sock = sock
                logger.info("Socket UDP bound en puerto %d", self.port)
                return
            except OSError as e:
                logger.warning("Intento %d/5 bind puerto %d falló: %s", attempt + 1, self.port, e)
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(2)
        logger.error("No se pudo bindear socket UDP en puerto %d. Heartbeats deshabilitados.", self.port)
        self.sock = None

    def _my_score(self) -> int:
        try:
            with open("/tmp/adhoc/my-score") as f:
                parts = f.read().strip().split("\t")
                return int(parts[2])
        except Exception:
            return 0

    def _get_my_ip(self) -> str:
        try:
            result = subprocess.run(
                ["ip", "addr", "show", "dev", IFACE],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "inet " in line:
                    return line.split()[1].split("/")[0]
        except Exception:
            pass
        return "0.0.0.0"

    def _heartbeat_payload(self, is_master: bool = False, reply: bool = False) -> bytes:
        msg = {
            "type": "heartbeat",
            "node_id": NODE_ID,
            "timestamp": time.time(),
            "score": self._my_score(),
            "ip": self._get_my_ip(),
            "is_master": is_master,
        }
        if reply:
            msg["reply"] = True
        if self.extra_heartbeat_fn:
            msg.update(self.extra_heartbeat_fn())
        return json.dumps(msg).encode("utf-8")

    def _send_unicast_heartbeat(self, peer_ip: str, is_master: bool = False, reply: bool = False):
        if self.sock is None or not peer_ip or peer_ip == "0.0.0.0":
            return
        try:
            self.sock.sendto(self._heartbeat_payload(is_master=is_master, reply=reply), (peer_ip, self.port))
        except OSError as e:
            logger.debug("Error enviando heartbeat unicast a %s: %s", peer_ip, e)

    def send_heartbeat(self, is_master: bool = False):
        if self.sock is None:
            return
        payload = self._heartbeat_payload(is_master=is_master)
        targets = [(BROADCAST_ADDR, self.port), (MULTI_ADDR, self.port)]
        # En IBSS algunos drivers/Fedora entregan broadcast de forma asimétrica.
        # Si ya conocemos algún peer, también mandamos heartbeat unicast para que
        # el otro lado nos vea sin depender de ping manual/ARP casual.
        with self.lock:
            for info in self.peers.values():
                peer_ip = info.get("ip")
                if peer_ip and peer_ip != "0.0.0.0":
                    targets.append((peer_ip, self.port))
        sent_any = False
        for target in targets:
            try:
                self.sock.sendto(payload, target)
                sent_any = True
            except OSError as e:
                # ENETUNREACH (101) es normal cuando no hay carrier/peers todavía en IBSS
                if e.errno == 101:
                    logger.debug("Heartbeat: sin ruta hacia %s", target[0])
                else:
                    logger.debug("Error enviando heartbeat a %s: %s", target[0], e)
        if not sent_any:
            logger.debug("No se pudo enviar heartbeat a ningún destino")

    def receiver_loop(self):
        if self.sock is None:
            logger.warning("Socket no disponible, receiver_loop deshabilitado.")
            return
        self.sock.settimeout(2.0)
        mc_joined = False
        last_mc_retry = 0.0
        while True:
            # Reintentar multicast join cada 10s hasta que el carrier suba
            if not mc_joined and time.time() - last_mc_retry > 10:
                try:
                    mreq = struct.pack("4sl", socket.inet_aton(MULTI_ADDR), socket.INADDR_ANY)
                    self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    mc_joined = True
                    logger.info("Multicast join exitoso en %s", MULTI_ADDR)
                except OSError:
                    last_mc_retry = time.time()
            try:
                data, addr = self.sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8"))
                msg_type = msg.get("type")

                if msg_type == "heartbeat" and msg.get("node_id") != NODE_ID:
                    nid = msg["node_id"]
                    peer_ip = msg.get("ip", addr[0])
                    peer_master = msg.get("is_master", False)
                    peer_score = msg.get("score", 0)
                    # Respuesta unicast inmediata y repetida: ayuda a que el emisor
                    # nos descubra aunque los broadcasts sean asimétricos en IBSS.
                    if not msg.get("reply"):
                        self._send_unicast_heartbeat(peer_ip, reply=True)
                    with self.lock:
                        is_new = nid not in self.peers
                        prev_master = self.peers.get(nid, {}).get("is_master")
                        self.peers[nid] = {
                            "ip": peer_ip,
                            "score": peer_score,
                            "songs": msg.get("songs", []),
                            "is_master": peer_master,
                            "current_song": msg.get("current_song", "Ninguna"),
                            "last_seen": time.time(),
                        }
                    if is_new:
                        logger.info("Peer descubierto: %s ip=%s score=%d master=%s",
                                    nid, peer_ip, peer_score, peer_master)
                    elif prev_master != peer_master:
                        logger.info("Peer %s cambió master: %s -> %s (score=%d)",
                                    nid, prev_master, peer_master, peer_score)

                elif msg_type == "ip_reassign" and msg.get("target_node_id") == NODE_ID:
                    new_ip = msg.get("new_ip")
                    logger.info("Recibida reasignación de IP a %s", new_ip)
                    self._change_ip(new_ip)

                elif msg_type == "song_request":
                    song = msg.get("song_name", "")
                    requester = msg.get("node_id", "unknown")
                    logger.info("Solicitud de canción '%s' desde %s", song, requester)
                    if self.on_song_request_fn:
                        self.on_song_request_fn(song)

            except socket.timeout:
                continue
            except Exception as e:
                logger.warning("receiver_loop error inesperado: %s", e)
                continue

    def _prune_stale_peers_locked(self, now: Optional[float] = None):
        """Elimina peers que ya no envían heartbeats. Requiere self.lock tomado."""
        now = now or time.time()
        dead = [
            nid for nid, info in self.peers.items()
            if now - info.get("last_seen", 0) > PEER_TIMEOUT
        ]
        for nid in dead:
            logger.info("Peer perdido (timeout %.0fs): %s", PEER_TIMEOUT, nid)
            del self.peers[nid]

    def cleanup_peers(self):
        with self.lock:
            self._prune_stale_peers_locked()

    def am_i_master(self, force_master: bool = False) -> bool:
        if force_master:
            return True
        my_score = self._my_score()
        with self.lock:
            if not self.peers:
                # Startup grace period: don't claim master for the first 10s.
                # This prevents a joining node from declaring itself master before
                # receiving heartbeats from the existing master in the network.
                if time.time() - self._start_time < 10:
                    return False
                return True
            for nid, info in self.peers.items():
                peer_score = info["score"]
                if peer_score > my_score:
                    return False
                # Tiebreaker: higher node_id string wins (deterministic on equal score)
                if peer_score == my_score and nid > NODE_ID:
                    return False
            return True

    def register_peer(self, info: Dict[str, Any], addr_ip: str = ""):
        """Registra/actualiza un peer anunciado por HTTP.

        Fallback para IBSS cuando UDP broadcast/unicast es asimétrico: si el
        cliente sí ve al master, le hace POST /api/register-peer y el master lo
        inserta aquí para que la UI/stream lo reconozcan inmediatamente.
        """
        nid = info.get("node_id")
        if not nid or nid == NODE_ID:
            return
        # Preferir la IP real de la conexión HTTP. En IBSS a veces el payload
        # trae una IP vieja/incorrecta, pero request.remote_addr es la ruta que
        # acaba de funcionar hacia este peer.
        peer_ip = addr_ip or info.get("ip")
        with self.lock:
            is_new = nid not in self.peers
            self.peers[nid] = {
                "ip": peer_ip,
                "score": info.get("score", 0),
                "songs": info.get("songs", []),
                "is_master": info.get("is_master", False),
                "current_song": info.get("current_song", "Ninguna"),
                "last_seen": time.time(),
            }
        if is_new:
            logger.info("Peer registrado vía HTTP: %s ip=%s", nid, peer_ip)

    def local_announcement(self, is_master: bool = False) -> Dict[str, Any]:
        payload = json.loads(self._heartbeat_payload(is_master=is_master).decode("utf-8"))
        payload["type"] = "peer_announce"
        payload["announce_ts"] = time.time()
        return payload

    def detect_ip_conflicts(self) -> list:
        conflicts = []
        with self.lock:
            ip_to_nodes: Dict[str, list] = {}
            for nid, info in self.peers.items():
                ip = info.get("ip", "")
                if ip:
                    ip_to_nodes.setdefault(ip, []).append(nid)
            for ip, nids in ip_to_nodes.items():
                if len(nids) >= 2:
                    conflicts.append((ip, nids[0], nids[1]))
        return conflicts

    def pick_free_ip(self) -> str:
        used = set()
        my_ip = self._get_my_ip()
        if my_ip:
            used.add(my_ip)
        with self.lock:
            for info in self.peers.values():
                ip = info.get("ip")
                if ip:
                    used.add(ip)
        for octet in range(10, 251):
            candidate = f"{IP_PREFIX}.{octet}"
            if candidate not in used:
                return candidate
        return f"{IP_PREFIX}.250"

    def send_ip_reassign(self, target_node_id: str, new_ip: str):
        if self.sock is None:
            return
        msg = {
            "type": "ip_reassign",
            "target_node_id": target_node_id,
            "new_ip": new_ip,
        }
        payload = json.dumps(msg).encode("utf-8")
        try:
            self.sock.sendto(payload, (BROADCAST_ADDR, self.port))
            self.sock.sendto(payload, (MULTI_ADDR, self.port))
        except OSError as e:
            logger.warning("Error enviando ip_reassign: %s", e)

    def send_song_request(self, song_name: str):
        if self.sock is None:
            return
        msg = {
            "type": "song_request",
            "node_id": NODE_ID,
            "song_name": song_name,
            "timestamp": time.time(),
        }
        payload = json.dumps(msg).encode("utf-8")
        try:
            self.sock.sendto(payload, (BROADCAST_ADDR, self.port))
            self.sock.sendto(payload, (MULTI_ADDR, self.port))
        except OSError as e:
            logger.warning("Error enviando song_request: %s", e)

    def _change_ip(self, new_ip: str):
        try:
            subprocess.run(["ip", "addr", "flush", "dev", IFACE], check=False, capture_output=True)
            subprocess.run(["ip", "addr", "add", f"{new_ip}/24", "dev", IFACE], check=False, capture_output=True)
            with open("/tmp/adhoc/my_ip", "w") as f:
                f.write(new_ip)
            logger.info("IP cambiada a %s", new_ip)
        except Exception as e:
            logger.error("Error cambiando IP: %s", e)

    def start(self):
        t_recv = threading.Thread(target=self.receiver_loop, daemon=True)
        t_recv.start()

    def get_peers_snapshot(self) -> Dict[str, Any]:
        """Devuelve peers activos, purgando antes los desconectados.

        Esto evita que la API/web siga mostrando nodos que salieron hasta que
        corra el hilo periódico de cleanup.
        """
        with self.lock:
            self._prune_stale_peers_locked()
            return {nid: dict(info) for nid, info in self.peers.items()}
