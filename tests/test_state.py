#!/usr/bin/env python3
"""
test_state.py — Pruebas del módulo de persistencia de estado.
"""

import os
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Forzar directorio de estado temporal
import node.state as node_state
node_state.STATE_DIR = Path(tempfile.mkdtemp())
node_state.STATE_FILE = node_state.STATE_DIR / "node-state.json"


def test_save_and_load():
    """Guardar y recuperar estado."""
    payload = {
        "cell_id": "02:aa:bb:cc:dd:ee",
        "is_master": True,
        "current_song": "song_01.mp3",
    }
    assert node_state.save(payload) is True

    loaded = node_state.load()
    assert loaded is not None
    assert loaded["cell_id"] == "02:aa:bb:cc:dd:ee"
    assert loaded["is_master"] is True
    assert loaded["current_song"] == "song_01.mp3"
    assert "timestamp" in loaded
    print("[PASS] test_save_and_load")


def test_stale_state():
    """Estado con más de 5 minutos se considera inválido."""
    # Guardar con timestamp viejo
    with open(node_state.STATE_FILE, "w") as f:
        import json
        json.dump({
            "cell_id": "old",
            "timestamp": time.time() - 400,  # > 300s
        }, f)

    loaded = node_state.load()
    assert loaded is None
    print("[PASS] test_stale_state")


def test_clear():
    """Eliminar estado."""
    node_state.save({"cell_id": "x"})
    assert node_state.STATE_FILE.exists()
    node_state.clear()
    assert not node_state.STATE_FILE.exists()
    print("[PASS] test_clear")


def test_load_missing():
    """Cargar cuando no existe archivo devuelve None."""
    node_state.clear()
    loaded = node_state.load()
    assert loaded is None
    print("[PASS] test_load_missing")


if __name__ == "__main__":
    test_save_and_load()
    test_stale_state()
    test_clear()
    test_load_missing()
