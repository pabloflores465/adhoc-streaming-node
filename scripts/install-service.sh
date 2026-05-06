#!/usr/bin/env bash
# install-service.sh — Registra el servicio systemd del nodo AD-HOC bajo demanda.
# El instalador Fedora NO lo instala automáticamente; usa este script si quieres systemd.
# Uso: sudo ./scripts/install-service.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_ROOT="/opt/adhoc-node"
SERVICE="adhoc-node.service"
UNIT_PATH="/etc/systemd/system/$SERVICE"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "[!] Ejecuta como root: sudo ./scripts/install-service.sh" >&2
    exit 1
fi

IFACE="${ADHOC_IFACE:-}"
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
IFACE="${IFACE:-wlan0}"

echo "[+] Instalando unit systemd en $UNIT_PATH..."
cp "$REPO_ROOT/systemd/$SERVICE" "$UNIT_PATH"
sed -i "s/ADHOC_IFACE=wlan0/ADHOC_IFACE=${IFACE}/" "$UNIT_PATH"

systemctl daemon-reload
systemctl disable "$SERVICE" 2>/dev/null || true

echo "[+] Servicio registrado en modo manual (NO habilitado al boot)."
echo "    Iniciar: sudo systemctl start $SERVICE"
echo "    Detener: sudo systemctl stop $SERVICE"
echo "    Logs:    sudo journalctl -u $SERVICE -f"
