#!/usr/bin/env bash
# remove-service.sh — Quita/desinstala el servicio systemd actual del nodo AD-HOC.
# No borra música, logs ni el repositorio instalado; solo detiene/deshabilita/elimina el unit.
# Uso: sudo ./scripts/remove-service.sh
set -euo pipefail

SERVICE="adhoc-node.service"
UNIT_PATH="/etc/systemd/system/$SERVICE"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "[!] Ejecuta como root: sudo ./scripts/remove-service.sh" >&2
    exit 1
fi

echo "[+] Deteniendo $SERVICE..."
systemctl stop "$SERVICE" 2>/dev/null || true

echo "[+] Deshabilitando $SERVICE..."
systemctl disable "$SERVICE" 2>/dev/null || true

if [ -f "$UNIT_PATH" ]; then
    echo "[+] Eliminando $UNIT_PATH..."
    rm -f "$UNIT_PATH"
else
    echo "[i] No existe $UNIT_PATH"
fi

echo "[+] Recargando systemd..."
systemctl daemon-reload
systemctl reset-failed "$SERVICE" 2>/dev/null || true

echo "[+] Servicio eliminado."
