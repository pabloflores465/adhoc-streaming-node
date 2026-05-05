#!/usr/bin/env bash
# adhoc-off-v2.sh — Restaura internet normal. Versión resistente para HP Pavilion 13.
# Uso: sudo ./adhoc-off-v2.sh
set -uo pipefail

IFACE="${ADHOC_IFACE:-}"
TIMEOUT_NM="${TIMEOUT_NM:-30}"
TIMEOUT_CONN="${TIMEOUT_CONN:-45}"
DRIVER_RELOAD="${DRIVER_RELOAD:-yes}"

# ─── helpers ───────────────────────────────────────────────────────────────
log()  { echo "[OFF-v2] $*"; }
warn() { echo "[OFF-v2] [!] $*" >&2; }

die()  { warn "$*"; exit 1; }

wait_for_iface_state() {
    local target="$1" max_wait="${2:-15}"
    local waited=0
    while [ "$waited" -lt "$max_wait" ]; do
        local state
        state=$(cat "/sys/class/net/$IFACE/operstate" 2>/dev/null || echo "unknown")
        if [ "$state" = "$target" ]; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

wait_for_nm_device() {
    local max_wait="${1:-15}"
    local waited=0
    while [ "$waited" -lt "$max_wait" ]; do
        if nmcli -t -f DEVICE device show "$IFACE" &>/dev/null; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

is_connected() {
    local state
    state=$(nmcli -t -f GENERAL.STATE device show "$IFACE" 2>/dev/null | cut -d: -f2 | tr -d ' ')
    [[ "$state" == "activated" || "$state" == "100" ]]
}

# ─── Auto-detectar interfaz inalámbrica ────────────────────────────────────
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
[ -z "$IFACE" ] && die "No se detectó interfaz inalámbrica. Especifica: sudo ADHOC_IFACE=wlanX ./adhoc-off-v2.sh"
log "Interfaz detectada: $IFACE"

# ─── Leer conexión guardada ANTES de tocar nada ────────────────────────────
SAVED_CON=""
[ -f /tmp/adhoc/nm_saved_connection ] && SAVED_CON=$(cat /tmp/adhoc/nm_saved_connection)

# ─── Quitar de firewalld ───────────────────────────────────────────────────
if command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --zone=trusted --remove-interface="$IFACE" 2>/dev/null || true
fi

# ─── Detener daemon ────────────────────────────────────────────────────────
if systemctl is-active --quiet adhoc-node.service 2>/dev/null; then
    log "Deteniendo adhoc-node.service..."
    systemctl stop adhoc-node.service && log "Daemon detenido." || warn "No se pudo detener daemon."
fi

# ─── Limpiar config NM permanente ──────────────────────────────────────────
NM_CONF="/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf"
[ -f "$NM_CONF" ] && { log "Eliminando $NM_CONF"; rm -f "$NM_CONF"; }

# ─── Salir de IBSS y matar wpa_supplicant huérfano ─────────────────────────
log "Saliendo de red IBSS..."
iw dev "$IFACE" ibss leave 2>/dev/null || true

# A veces wpa_supplicant se queda atado a la interfaz y bloquea NM
pkill -f "wpa_supplicant.*$IFACE" 2>/dev/null || true
sleep 1

# ─── Reset completo de interfaz ────────────────────────────────────────────
log "Bajando interfaz..."
ip link set "$IFACE" down 2>/dev/null || true
sleep 2

log "Limpiando IPs..."
ip addr flush dev "$IFACE" 2>/dev/null || true

log "Forzando modo managed..."
iw dev "$IFACE" set type managed 2>/dev/null || true
sleep 1

# Desbloquear por si rfkill la bloqueó
rfkill unblock wifi 2>/dev/null || true

log "Subiendo interfaz..."
ip link set "$IFACE" up 2>/dev/null || true
sleep 2

# Verificar que levantó; si no, forzar recarga de driver
if ! wait_for_iface_state "up" 8; then
    warn "Interfaz no levantó. Estado: $(cat /sys/class/net/$IFACE/operstate 2>/dev/null || echo '??')"

    if [ "$DRIVER_RELOAD" = "yes" ]; then
        # Detectar driver del módulo
        DRIVER=$(readlink -f "/sys/class/net/$IFACE/device/driver" 2>/dev/null | xargs basename 2>/dev/null || true)
        if [ -n "$DRIVER" ]; then
            warn "Recargando driver: $DRIVER"
            modprobe -r "$DRIVER" 2>/dev/null || true
            sleep 2
            modprobe "$DRIVER" 2>/dev/null || true
            sleep 3

            # Re-detectar interfaz (puede cambiar nombre)
            IFACE=""
            for _dev in /sys/class/net/*/wireless; do
                [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
            done
            [ -z "$IFACE" ] && die "Interfaz desapareció tras recargar driver."
            log "Nueva interfaz tras recarga: $IFACE"
            ip link set "$IFACE" up 2>/dev/null || true
            sleep 2
        fi
    fi
fi

# ─── Devolver a NetworkManager ─────────────────────────────────────────────
log "Devolviendo $IFACE a NetworkManager..."
nmcli device set "$IFACE" managed yes 2>/dev/null || true
sleep 2

# En lugar de reiniciar NM completo (lento y problemático en HP Pavilion),
# primero intentamos re-escanear sin restart
log "Refrescando estado en NetworkManager..."
nmcli device wifi rescan ifname "$IFACE" 2>/dev/null || true
sleep 2

# Si NM aún no ve el dispositivo bien, AHORA sí reiniciamos
if ! wait_for_nm_device "$TIMEOUT_NM"; then
    warn "NM no reconoce $IFACE. Reiniciando NetworkManager..."
    systemctl restart NetworkManager
    sleep 4
    if ! wait_for_nm_device "$TIMEOUT_NM"; then
        die "NetworkManager sigue sin ver $IFACE tras reinicio. Revisa 'dmesg | tail -30'"
    fi
fi

# ─── Esperar a que NM esté listo para conectar ─────────────────────────────
log "Esperando que NM esté disponible..."
local_state=""
waited=0
while [ "$waited" -lt 15 ]; do
    local_state=$(nmcli -t -f GENERAL.STATE device show "$IFACE" 2>/dev/null | cut -d: -f2 | tr -d ' ')
    if [ -n "$local_state" ]; then
        break
    fi
    sleep 1
    waited=$((waited + 1))
done

# ─── Reconectar ────────────────────────────────────────────────────────────
if [ -n "$SAVED_CON" ]; then
    log "Reconectando a: '$SAVED_CON'"
    nmcli con up "$SAVED_CON" 2>/dev/null || true
else
    log "Sin conexión guardada. Activando auto-conexión..."
    nmcli device connect "$IFACE" 2>/dev/null || true
fi

# ─── Esperar conexión con timeout ──────────────────────────────────────────
log "Esperando conexión (max ${TIMEOUT_CONN}s)..."
waited=0
while [ "$waited" -lt "$TIMEOUT_CONN" ]; do
    if is_connected; then
        log "=== CONECTADO ==="
        break
    fi
    sleep 1
    waited=$((waited + 1))
done

if ! is_connected; then
    warn "No se conectó automáticamente en ${TIMEOUT_CONN}s."
    # Fallback: lista redes disponibles
    log "Redes disponibles:"
    nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list ifname "$IFACE" 2>/dev/null | head -10 || true
    echo ""
    warn "Intenta manualmente: nmcli device wifi connect <SSID> --ask"
fi

# ─── Limpiar temporales ────────────────────────────────────────────────────
rm -f /tmp/adhoc/my_ip /tmp/adhoc/cell_id /tmp/adhoc/nm_saved_connection /tmp/adhoc-master.flag

echo ""
log "=== RESUMEN ==="
nmcli device status | grep -E "DEVICE|$IFACE" || true
echo ""
