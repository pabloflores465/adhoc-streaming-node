#!/usr/bin/env bash
set -euo pipefail

# streaming-server.sh — Inicia servidor de streaming UDP multicast con ffmpeg

SONG="$1"
MULTI_ADDR="${ADHOC_MULTI:-239.255.42.42}"
PORT="${ADHOC_PORT:-5004}"
IFACE="${ADHOC_IFACE:-wlan0}"

if [ ! -f "$SONG" ]; then
    echo "[STREAM-SRV] ERROR: Archivo no existe: $SONG" >&2
    exit 1
fi

echo "[STREAM-SRV] Streaming: $SONG → ${MULTI_ADDR}:${PORT}"

exec ffmpeg -re -i "$SONG" \
    -c:a libmp3lame -b:a 192k \
    -f mpegts "udp://${MULTI_ADDR}:${PORT}?ttl=1&pkt_size=1316"
