#!/usr/bin/env python3
"""
test_api.py — Pruebas de la API web Flask.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ["ADHOC_MUSIC"] = "/tmp/test_music"
os.environ["NODE_ID"] = "testnode"
os.environ["ADHOC_MULTI"] = "239.255.99.99"
os.environ["ADHOC_PORT"] = "59999"

from web.app import app, _daemon_state


class FakeDaemon:
    """Simula el estado mínimo del daemon para las pruebas."""

    def __init__(self):
        self.forced = None
        self.master = False
        self.paused = False

    def status(self):
        return {
            "node_id": "testnode",
            "is_master": self.master,
            "cell_id": "02:aa:bb:cc:dd:ee",
            "tx_rate": "54 Mb/s",
            "peer_count": 2,
            "peers": {
                "peer1": {"ip": "10.0.0.2", "score": 500, "songs": ["a.mp3"]},
                "peer2": {"ip": "10.0.0.3", "score": 300, "songs": ["b.mp3", "c.mp3"]},
            },
            "signal_levels": {"aa:bb:cc:dd:ee:ff": "-45 dBm"},
            "modulation": "OFDM",
            "local_songs": ["local1.mp3", "local2.mp3"],
            "current_streaming_song": "local1.mp3",
            "paused": self.paused,
            "all_network_songs": [
                ("local1.mp3", "testnode", True),
                ("local2.mp3", "testnode", True),
                ("a.mp3", "peer1", False),
                ("b.mp3", "peer2", False),
                ("c.mp3", "peer2", False),
            ],
            "system": {
                "cpu_percent": 12.5,
                "ram_available_mb": 2048,
                "load_avg": [0.5, 0.4, 0.3],
            },
        }

    def force_song(self, name):
        self.forced = name
        return True

    def force_master(self):
        self.master = True

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused


def test_api_status():
    fake = FakeDaemon()
    _daemon_state["status_fn"] = fake.status
    _daemon_state["force_song_fn"] = fake.force_song
    _daemon_state["force_master_fn"] = fake.force_master
    _daemon_state["toggle_pause_fn"] = fake.toggle_pause

    client = app.test_client()

    # Status JSON
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["node_id"] == "testnode"
    assert data["is_master"] is False
    assert len(data["peers"]) == 2
    print("[PASS] test_api_status")

    # Dashboard HTML
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "local1.mp3" in html
    assert "peer1" in html
    print("[PASS] test_dashboard_html")

    # Force song
    resp = client.post("/api/force-song", data={"song": "cancion_test.mp3"})
    assert resp.status_code == 200
    assert fake.forced == "cancion_test.mp3"
    print("[PASS] test_force_song")

    # Force master
    resp = client.post("/api/force-master")
    assert resp.status_code == 200
    assert fake.master is True
    print("[PASS] test_force_master")

    # Toggle pause
    assert fake.paused is False
    resp = client.post("/api/toggle-pause")
    assert resp.status_code == 200
    assert fake.paused is True
    resp = client.post("/api/toggle-pause")
    assert resp.status_code == 200
    assert fake.paused is False
    print("[PASS] test_toggle_pause")

    # Serve music (existente)
    music_dir = Path("/tmp/test_music")
    music_dir.mkdir(exist_ok=True)
    (music_dir / "test_song.mp3").write_text("fake mp3 data")
    resp = client.get("/music/test_song.mp3")
    assert resp.status_code == 200
    print("[PASS] test_serve_music")

    # Serve music (no existe)
    resp = client.get("/music/no_existe.mp3")
    assert resp.status_code == 404
    print("[PASS] test_serve_music_404")

    # Path traversal
    resp = client.get("/music/../../../etc/passwd")
    assert resp.status_code in (403, 404)
    print("[PASS] test_serve_music_traversal")


if __name__ == "__main__":
    test_api_status()
