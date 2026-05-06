#!/usr/bin/env bash
# start-node.sh — Arranca manualmente el nodo AD-HOC.
# Uso: sudo ./scripts/start-node.sh
set -euo pipefail

systemctl daemon-reload
systemctl start adhoc-node.service

echo "[+] Nodo AD-HOC iniciado manualmente."
echo "    Estado: sudo systemctl status adhoc-node.service"
echo "    Logs:   sudo journalctl -u adhoc-node.service -f"
