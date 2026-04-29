#!/usr/bin/env python3
"""
monitor.py — Recolecta métricas de red AD-HOC y estado del nodo.
"""

import os
import subprocess
import psutil
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

IFACE = os.environ.get("ADHOC_IFACE", "wlan0")
MUSIC_DIR = os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music")
_IW_TIMEOUT = 4  # segundos máximos para cualquier llamada a iw


def _run_iw(*args) -> Optional[str]:
    """Ejecuta un comando iw con timeout. Devuelve stdout o None si falla/timeout."""
    try:
        result = subprocess.run(
            ["iw", "dev", IFACE] + list(args),
            capture_output=True, text=True, timeout=_IW_TIMEOUT
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("iw %s: %s", " ".join(args), e)
        return None


def get_station_dump() -> List[Dict[str, Any]]:
    out = _run_iw("station", "dump")
    if not out:
        return []
    peers = []
    current: Dict[str, Any] = {}
    for line in out.splitlines():
        if line.startswith("Station"):
            if current:
                peers.append(current)
            current = {"mac": line.split()[1]}
        elif ":" in line and current:
            key, val = line.split(":", 1)
            current[key.strip().lower().replace(" ", "_")] = val.strip()
    if current:
        peers.append(current)
    return peers


def get_link_info() -> Dict[str, Any]:
    out = _run_iw("link")
    if not out:
        return {}
    info = {}
    for line in out.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            info[key.strip().lower().replace(" ", "_")] = val.strip()
    return info


def _extract_metrics(station_dump: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extrae tx_rate, signal_levels y modulation de un station_dump ya obtenido."""
    rates = []
    signal_levels = {}
    mods = []

    for p in station_dump:
        mac = p.get("mac", "?")
        rx = p.get("rx_bitrate", "")
        tx = p.get("tx_bitrate", "")
        sig = p.get("signal", "N/A")

        if rx:
            rates.append(f"RX {rx}")
        if tx:
            rates.append(f"TX {tx}")
        signal_levels[mac] = sig
        if "MCS" in rx:
            mods.append(f"{mac}: {rx}")

    tx_rate = "; ".join(rates) if rates else get_link_info().get("rx_bitrate", "N/A")
    modulation = "; ".join(mods) if mods else "OFDM/CCK (inferido por canal 2.4GHz)"

    return {"tx_rate": tx_rate, "signal_levels": signal_levels, "modulation": modulation}


def get_local_songs() -> List[str]:
    d = Path(MUSIC_DIR)
    if not d.exists():
        return []
    exts = {".mp3", ".ogg", ".flac", ".wav", ".m4a", ".aac"}
    return sorted([f.name for f in d.iterdir() if f.suffix.lower() in exts])


def get_cell_id() -> str:
    try:
        with open("/tmp/adhoc/cell_id") as f:
            return f.read().strip()
    except Exception:
        return "N/A"


def get_system_stats() -> Dict[str, Any]:
    load = os.getloadavg()
    return {
        "cpu_percent": psutil.cpu_percent(),   # no-blocking, usa último valor cacheado
        "ram_percent": psutil.virtual_memory().percent,
        "ram_available_mb": psutil.virtual_memory().available // (1024 * 1024),
        "load_avg": f"{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}",
    }


def build_status(master: bool, current_song: str, peers_data: Dict[str, Any]) -> Dict[str, Any]:
    """Construye objeto de estado completo. Llama a iw una sola vez por request."""
    station_dump = get_station_dump()   # una sola llamada, se reutiliza abajo
    metrics = _extract_metrics(station_dump)

    return {
        "node_id": os.environ.get("NODE_ID", "unknown"),
        "hostname": os.uname().nodename,
        "is_master": master,
        "cell_id": get_cell_id(),
        "tx_rate": metrics["tx_rate"],
        "peers": peers_data,
        "active_peers": list(peers_data.keys()),
        "peer_count": len(peers_data),
        "signal_levels": metrics["signal_levels"],
        "modulation": metrics["modulation"],
        "local_songs": get_local_songs(),
        "current_song": current_song,
        "current_streaming_song": current_song,
        "system": get_system_stats(),
    }
