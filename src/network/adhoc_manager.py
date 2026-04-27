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

IFACE = os.environ.get("ADHOC_IFACE", "wlan0")
MULTI_ADDR = os.environ.get("ADHOC_MULTI", "239.255.42.42")
PORT = int(os.environ.get("ADHOC_PORT", "5004"))
HEARTBEAT_PORT = PORT + 1
BROADCAST_ADDR = "255.255.255.255"
IP_PREFIX = os.environ.get("ADHOC_NET", "192.168.99")

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
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        self.sock.bind(("0.0.0.0", self.port))

        mreq = struct.pack("4sl", socket.inet_aton(MULTI_ADDR), socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    def _my_score(self) -> int:
        try:
            with open("/tmp/adhoc/my-score") as f:
                parts = f.read().strip().split("\t")
                return int(parts[2])
        except Exception:
            return 0

    def _get_my_ip(self) -> str:
        try:
            out = subprocess.check_output(["ip", "addr", "show", "dev", IFACE], text=True)
            for line in out.splitlines():
                if "inet " in line:
                    return line.split()[1].split("/")[0]
        except Exception:
            pass
        return "0.0.0.0"

    def send_heartbeat(self, is_master: bool = False):
        msg = {
            "type": "heartbeat",
            "node_id": NODE_ID,
            "timestamp": time.time(),
            "score": self._my_score(),
            "ip": self._get_my_ip(),
            "is_master": is_master,
        }
        if self.extra_heartbeat_fn:
            msg.update(self.extra_heartbeat_fn())
        payload = json.dumps(msg).encode("utf-8")
        self.sock.sendto(payload, (BROADCAST_ADDR, self.port))
        self.sock.sendto(payload, (MULTI_ADDR, self.port))

    def receiver_loop(self):
        self.sock.settimeout(2.0)
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8"))
                msg_type = msg.get("type")

                if msg_type == "heartbeat" and msg.get("node_id") != NODE_ID:
                    with self.lock:
                        self.peers[msg["node_id"]] = {
                            "ip": msg.get("ip", addr[0]),
                            "score": msg.get("score", 0),
                            "songs": msg.get("songs", []),
                            "last_seen": time.time(),
                        }

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
            except Exception:
                continue

    def cleanup_peers(self):
        now = time.time()
        with self.lock:
            dead = [nid for nid, info in self.peers.items() if now - info["last_seen"] > 15]
            for nid in dead:
                del self.peers[nid]

    def am_i_master(self, force_master: bool = False) -> bool:
        if force_master:
            return True
        my_score = self._my_score()
        with self.lock:
            if not self.peers:
                return True
            for info in self.peers.values():
                if info["score"] > my_score:
                    return False
            return True

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
        msg = {
            "type": "ip_reassign",
            "target_node_id": target_node_id,
            "new_ip": new_ip,
        }
        payload = json.dumps(msg).encode("utf-8")
        self.sock.sendto(payload, (BROADCAST_ADDR, self.port))
        self.sock.sendto(payload, (MULTI_ADDR, self.port))

    def send_song_request(self, song_name: str):
        msg = {
            "type": "song_request",
            "node_id": NODE_ID,
            "song_name": song_name,
            "timestamp": time.time(),
        }
        payload = json.dumps(msg).encode("utf-8")
        self.sock.sendto(payload, (BROADCAST_ADDR, self.port))
        self.sock.sendto(payload, (MULTI_ADDR, self.port))

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
        with self.lock:
            return dict(self.peers)
