#!/usr/bin/env python3
"""
state.py — Persistencia de estado del nodo en JSON.

Guarda/recupera:
- cell_id (BSSID de la celda IBSS actual)
- is_master (rol previo)
- last_song (última canción en streaming)
- timestamp (último guardado)
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

STATE_DIR = Path("/opt/adhoc-node/state")
STATE_FILE = STATE_DIR / "node-state.json"


def _ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def save(state: Dict[str, Any]) -> bool:
    """Guarda estado en disco. Devuelve True si éxito."""
    try:
        _ensure_dir()
        payload = {
            **state,
            "timestamp": time.time(),
        }
        # Write atomically
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(STATE_FILE)
        return True
    except Exception as e:
        return False


def load() -> Optional[Dict[str, Any]]:
    """Carga estado desde disco. Devuelve None si no existe o es inválido."""
    try:
        if not STATE_FILE.exists():
            return None
        with open(STATE_FILE) as f:
            data = json.load(f)
        # Validar antigüedad: si tiene > 5 minutos, considerar stale
        if time.time() - data.get("timestamp", 0) > 300:
            return None
        return data
    except Exception:
        return None


def clear() -> bool:
    """Elimina archivo de estado."""
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        return True
    except Exception:
        return False
