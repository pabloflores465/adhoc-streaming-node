#!/usr/bin/env python3
"""
test_network.py — Pruebas del módulo de red AdhocManager.
"""

import os
import sys
import json
import socket
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from network.adhoc_manager import AdhocManager

os.environ["ADHOC_MULTI"] = "239.255.99.99"
os.environ["ADHOC_IFACE"] = "lo"
os.environ["ADHOC_NET"] = "10.254.0"
os.environ["NODE_ID"] = "testnode"


def test_heartbeat_exchange():
    """Un manager recibe heartbeats de un socket emulado y detecta peers."""
    received = {}

    def on_song(name):
        received["song"] = name

    m = AdhocManager(on_song_request_fn=on_song, port=54321)
    m.start()

    # Socket emisor
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Enviar heartbeat
    msg = {
        "type": "heartbeat",
        "node_id": "peer99",
        "timestamp": time.time(),
        "score": 555,
        "ip": "10.254.0.99",
        "songs": ["a.mp3", "b.mp3"],
    }
    for _ in range(3):
        sender.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", 54321))
        time.sleep(0.2)

    time.sleep(0.5)
    peers = m.get_peers_snapshot()
    assert "peer99" in peers, f"Peers: {peers}"
    assert peers["peer99"]["score"] == 555
    assert peers["peer99"]["songs"] == ["a.mp3", "b.mp3"]

    # Enviar song_request
    req = {
        "type": "song_request",
        "node_id": "other",
        "song_name": "test_song.mp3",
        "timestamp": time.time(),
    }
    for _ in range(3):
        sender.sendto(json.dumps(req).encode("utf-8"), ("127.0.0.1", 54321))
        time.sleep(0.2)

    time.sleep(0.5)
    assert received.get("song") == "test_song.mp3"

    # Test IP conflict detection
    with m.lock:
        m.peers["node_a"] = {"ip": "10.254.0.50", "score": 100, "last_seen": time.time()}
        m.peers["node_b"] = {"ip": "10.254.0.50", "score": 200, "last_seen": time.time()}
    conflicts = m.detect_ip_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0][0] == "10.254.0.50"

    # Test pick_free_ip (el prefijo depende de ADHOC_NET en tiempo de import)
    free = m.pick_free_ip()
    assert free.count(".") == 3
    assert free != "10.254.0.50"

    sender.close()
    m.sock.close()
    print("[PASS] test_heartbeat_exchange")


if __name__ == "__main__":
    test_heartbeat_exchange()
