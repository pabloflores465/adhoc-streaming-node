#!/usr/bin/env python3
"""
monitor.py — Recolecta métricas de red AD-HOC y estado del nodo.
"""

import os
import re
import json
import subprocess
import psutil
import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

IFACE = os.environ.get("ADHOC_IFACE", "wlan0")
MUSIC_DIR = os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music")


def get_station_dump() -> List[Dict[str, Any]]:
    """Parsea `iw dev <iface> station dump` para obtener peers."""
    peers = []
    try:
        out = subprocess.check_output(["iw", "dev", IFACE, "station", "dump"], text=True)
    except subprocess.CalledProcessError:
        logger.debug("iw station dump falló (posiblemente sin peers)")
        return peers

    current = {}
    for line in out.splitlines():
        if line.startswith("Station"):
            if current:
                peers.append(current)
            mac = line.split()[1]
            current = {"mac": mac}
        elif ":" in line and current is not None:
            key, val = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            current[key] = val.strip()
    if current:
        peers.append(current)
    return peers


def get_link_info() -> Dict[str, Any]:
    """Parsea `iw dev <iface> link` para info local de enlace."""
    info = {}
    try:
        out = subprocess.check_output(["iw", "dev", IFACE, "link"], text=True)
    except subprocess.CalledProcessError:
        return info

    for line in out.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            info[key] = val.strip()
    return info


def get_tx_rate() -> str:
    """Extrae tasa de transmisión activa del link o station dump."""
    peers = get_station_dump()
    rates = []
    for p in peers:
        rx = p.get("rx_bitrate", "")
        tx = p.get("tx_bitrate", "")
        if rx:
            rates.append(f"RX {rx}")
        if tx:
            rates.append(f"TX {tx}")
    if rates:
        return "; ".join(rates)
    link = get_link_info()
    return link.get("rx_bitrate", "N/A")


def get_signal_levels() -> Dict[str, str]:
    """Devuelve nivel de señal por MAC de peer."""
    peers = get_station_dump()
    return {p["mac"]: p.get("signal", "N/A") for p in peers}


def get_modulation() -> str:
    """Extrae modulación del link info o station dump."""
    # iw no da modulación directamente, inferimos del bitrate + MCS si existe
    peers = get_station_dump()
    mods = []
    for p in peers:
        rx = p.get("rx_bitrate", "")
        if "MCS" in rx:
            mods.append(f"{p['mac']}: {rx}")
    if mods:
        return "; ".join(mods)
    return "OFDM/CCK (inferido por canal 2.4GHz)"


def get_local_songs() -> List[str]:
    """Lista canciones en directorio local."""
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
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_available_mb": psutil.virtual_memory().available // (1024 * 1024),
        "load_avg": os.getloadavg(),
    }


def build_status(master: bool, current_song: str, peers_data: Dict[str, Any]) -> Dict[str, Any]:
    """Construye objeto de estado completo para la API."""
    return {
        "node_id": os.environ.get("NODE_ID", "unknown"),
        "hostname": os.uname().nodename,
        "is_master": master,
        "cell_id": get_cell_id(),
        "tx_rate": get_tx_rate(),
        "active_peers": list(peers_data.keys()),
        "peer_count": len(peers_data),
        "signal_levels": get_signal_levels(),
        "modulation": get_modulation(),
        "local_songs": get_local_songs(),
        "current_streaming_song": current_song,
        "system": get_system_stats(),
    }
