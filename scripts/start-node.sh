#!/usr/bin/env bash
# start-node.sh — Arranca manualmente el nodo AD-HOC.
# Uso: sudo ./scripts/start-node.sh
set -euo pipefail

if [ ! -f /etc/systemd/system/adhoc-node.service ]; then
    echo "[i] Servicio no registrado; instalándolo en modo manual..."
    "$(dirname "$0")/install-service.sh"
fi

systemctl daemon-reload
systemctl start adhoc-node.service

echo "[+] Nodo AD-HOC iniciado manualmente."
echo "    Estado: sudo systemctl status adhoc-node.service"
echo "    Logs:   sudo journalctl -u adhoc-node.service -f"
