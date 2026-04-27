#!/usr/bin/env bash
set -euo pipefail

# streaming-client.sh — Reproduce el stream multicast entrante

MULTI_ADDR="${ADHOC_MULTI:-239.255.42.42}"
PORT="${ADHOC_PORT:-5004}"
PLAYER="${ADHOC_PLAYER:-mpv}"

echo "[STREAM-CLI] Escuchando ${MULTI_ADDR}:${PORT} con $PLAYER"

if command -v "$PLAYER" >/dev/null 2>&1; then
    exec "$PLAYER" "udp://${MULTI_ADDR}:${PORT}"
else
    # Fallback a ffplay
    exec ffplay -nodisp -autoexit "udp://${MULTI_ADDR}:${PORT}"
fi
