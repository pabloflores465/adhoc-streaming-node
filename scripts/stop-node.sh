#!/usr/bin/env bash
# stop-node.sh — Detiene manualmente el nodo AD-HOC.
# Uso: sudo ./scripts/stop-node.sh
set -euo pipefail

systemctl stop adhoc-node.service 2>/dev/null || true

echo "[+] Nodo AD-HOC detenido."
