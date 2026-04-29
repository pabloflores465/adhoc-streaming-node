#!/usr/bin/env bash
# adhoc-off.sh — Restaura internet normal. Revierte todo lo que hizo adhoc-on.sh.
# Uso: sudo ./scripts/adhoc-off.sh
set -euo pipefail

IFACE="${ADHOC_IFACE:-}"

# ─── Auto-detectar interfaz inalámbrica ────────────────────────────────────
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
if [ -z "$IFACE" ]; then
    echo "[!] No se detectó interfaz inalámbrica. Especifica: sudo ADHOC_IFACE=wlanX ./adhoc-off.sh"
    exit 1
fi
echo "[OFF] Restaurando interfaz: $IFACE"

# ─── Eliminar config permanente de NM si fue creada ────────────────────────
NM_CONF="/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf"
if [ -f "$NM_CONF" ]; then
    echo "[OFF] Eliminando config NM permanente: $NM_CONF"
    rm -f "$NM_CONF"
fi

# ─── Salir de la red IBSS ──────────────────────────────────────────────────
echo "[OFF] Saliendo de red IBSS..."
iw dev "$IFACE" ibss leave 2>/dev/null || true

# ─── Limpiar y resetear interfaz a managed ─────────────────────────────────
ip link set "$IFACE" down 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true

# ─── Devolver control a NetworkManager ─────────────────────────────────────
echo "[OFF] Devolviendo $IFACE a NetworkManager..."
nmcli device set "$IFACE" managed yes 2>/dev/null || true

# ─── Reiniciar NM para aplicar cambios ─────────────────────────────────────
echo "[OFF] Reiniciando NetworkManager..."
systemctl restart NetworkManager
sleep 3

# ─── Reconectar a la red WiFi anterior ─────────────────────────────────────
SAVED_CON=""
if [ -f /tmp/adhoc/nm_saved_connection ]; then
    SAVED_CON=$(cat /tmp/adhoc/nm_saved_connection)
fi

if [ -n "$SAVED_CON" ]; then
    echo "[OFF] Reconectando a conexión anterior: '$SAVED_CON'"
    nmcli con up "$SAVED_CON" 2>/dev/null \
        && echo "[OFF] Reconectado exitosamente." \
        || echo "[OFF] No se pudo reconectar automáticamente. Usa 'nmcli device wifi connect <SSID>'."
else
    echo "[OFF] Sin conexión guardada. NetworkManager intentará auto-conectar."
fi

# ─── Limpiar archivos temporales ───────────────────────────────────────────
rm -f /tmp/adhoc/my_ip /tmp/adhoc/cell_id /tmp/adhoc/nm_saved_connection
rm -f /tmp/adhoc-master.flag

echo ""
echo "[OFF] === INTERNET RESTAURADO ==="
echo "     Interfaz $IFACE devuelta a NetworkManager."
echo ""
nmcli device status | grep -E "DEVICE|$IFACE" || true
