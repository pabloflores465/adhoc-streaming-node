#!/usr/bin/env python3
"""
test_streamer.py — Pruebas del módulo Streamer.
"""

import os
import sys
import time
import tempfile
import subprocess
import http.server
import threading
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from streaming.streamer import Streamer

os.environ["ADHOC_MULTI"] = "239.255.99.99"
os.environ["ADHOC_PORT"] = "59999"
os.environ["ADHOC_MUSIC"] = "/tmp/test_music"


def _generate_wav(path: Path):
    """Genera WAV mínimo válido con Python puro (2 segundos de silencio)."""
    sample_rate = 44100
    duration = 2
    num_samples = sample_rate * duration
    byte_rate = sample_rate * 1 * 1  # mono, 8-bit
    data_size = num_samples
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 1, 8))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x80" * data_size)


def setup_module():
    """Generar audio dummy para pruebas."""
    music_dir = Path("/tmp/test_music")
    music_dir.mkdir(exist_ok=True)
    out = music_dir / "dummy.wav"
    _generate_wav(out)
    print(f"[SETUP] Audio dummy en {out}")


FFMPEG_AVAILABLE = subprocess.call(["which", "ffmpeg"], stdout=subprocess.DEVNULL) == 0


def test_streamer_local():
    """Streamer inicia servidor con archivo local y detecta EOF."""
    if not FFMPEG_AVAILABLE:
        print("[SKIP] test_streamer_local — ffmpeg no disponible")
        return

    eof_called = threading.Event()
    song_name = None

    def on_song(name):
        nonlocal song_name
        song_name = name

    def on_eof():
        eof_called.set()

    s = Streamer(song_change_callback=on_song, on_eof_callback=on_eof)
    path = Path("/tmp/test_music/dummy.wav")

    s.start_server(path)
    assert s.is_running()
    assert song_name == "dummy.wav"

    # Esperar EOF (archivo corto, ~2s)
    eof_called.wait(timeout=10)
    assert eof_called.is_set()
    print("[PASS] test_streamer_local")


def test_streamer_url_relay():
    """Streamer inicia servidor desde URL HTTP (simula peer remoto)."""
    if not FFMPEG_AVAILABLE:
        print("[SKIP] test_streamer_url_relay — ffmpeg no disponible")
        return

    music_dir = Path("/tmp/test_music")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    try:
        eof_called = threading.Event()
        s = Streamer(on_eof_callback=lambda: eof_called.set())
        url = f"http://127.0.0.1:{port}/dummy.wav"
        s.start_server_from_url(url, "remote_dummy.wav")
        assert s.is_running()
        assert s.current_song == "remote_dummy.wav"

        eof_called.wait(timeout=10)
        assert eof_called.is_set()
        print("[PASS] test_streamer_url_relay")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    setup_module()
    test_streamer_local()
    test_streamer_url_relay()
