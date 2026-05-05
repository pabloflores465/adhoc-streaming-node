#!/usr/bin/env bash
# adhoc-off-v3.sh — Restaura internet. Ultra-resiliente para HP Pavilion 13.
# Soluciona: "setting up network address" / NM atascado en configuración IP.
# Uso: sudo ./adhoc-off-v3.sh
set -uo pipefail

IFACE="${ADHOC_IFACE:-}"
TIMEOUT_NM="${TIMEOUT_NM:-20}"
TIMEOUT_CONN="${TIMEOUT_CONN:-40}"
DRIVER_RELOAD="${DRIVER_RELOAD:-yes}"

# ─── helpers ───────────────────────────────────────────────────────────────
log()  { echo "[OFF-v3] $*"; }
warn() { echo "[OFF-v3] [!] $*" >&2; }
die()  { warn "$*"; exit 1; }

nm_state() {
    nmcli -t -f GENERAL.STATE device show "$IFACE" 2>/dev/null | cut -d: -f2 | tr -d ' '
}

is_connected() {
    local s
    s=$(nm_state)
    [[ "$s" == "activated" || "$s" == "100" ]]
}

is_disconnected() {
    local s
    s=$(nm_state)
    [[ "$s" == "disconnected" || "$s" == "30" || -z "$s" ]]
}

wait_for_state() {
    local target="$1" max="${2:-15}"
    local w=0
    while [ "$w" -lt "$max" ]; do
        local s
        s=$(nm_state)
        case "$target" in
            disconnected)
                [[ "$s" == "disconnected" || "$s" == "30" || "$s" == "unavailable" || -z "$s" ]] && return 0 ;;
            activated)
                [[ "$s" == "activated" || "$s" == "100" ]] && return 0 ;;
            *)
                [[ "$s" == "$target" ]] && return 0 ;;
        esac
        sleep 1
        w=$((w + 1))
    done
    return 1
}

iface_exists() { [ -e "/sys/class/net/$IFACE" ]; }

# ─── Auto-detectar interfaz ────────────────────────────────────────────────
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
[ -z "$IFACE" ] && die "No se detectó interfaz inalámbrica. Usa: sudo ADHOC_IFACE=wlanX ./adhoc-off-v3.sh"
log "Interfaz: $IFACE"

# ─── Leer datos guardados ANTES de tocar nada ──────────────────────────────
SAVED_CON=""
SAVED_SSID=""
[ -f /tmp/adhoc/nm_saved_connection ] && SAVED_CON=$(cat /tmp/adhoc/nm_saved_connection)
if [ -n "$SAVED_CON" ]; then
    SAVED_SSID=$(nmcli -t -f 802-11-wireless.ssid connection show "$SAVED_CON" 2>/dev/null || true)
fi
[ -n "$SAVED_SSID" ] && log "SSID guardado: '$SAVED_SSID' (perfil: '$SAVED_CON')"

# ─── Limpiar firewalld ─────────────────────────────────────────────────────
if command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --zone=trusted --remove-interface="$IFACE" 2>/dev/null || true
fi

# ─── Detener daemon ────────────────────────────────────────────────────────
if systemctl is-active --quiet adhoc-node.service 2>/dev/null; then
    log "Deteniendo adhoc-node.service..."
    systemctl stop adhoc-node.service || true
fi

# ─── Limpiar config NM permanente ──────────────────────────────────────────
NM_CONF="/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf"
[ -f "$NM_CONF" ] && { log "Eliminando $NM_CONF"; rm -f "$NM_CONF"; }

# ─── Desconectar y liberar la interfaz de NM INMEDIATAMENTE ────────────────
log "Desconectando $IFACE de NM..."
nmcli device disconnect "$IFACE" 2>/dev/null || true
nmcli device set "$IFACE" managed no 2>/dev/null || true
sleep 2

# ─── Salir de IBSS y matar wpa_supplicant / dhcp ───────────────────────────
log "Saliendo de IBSS..."
iw dev "$IFACE" ibss leave 2>/dev/null || true

log "Matando wpa_supplicant y clientes DHCP..."
pkill -f "wpa_supplicant.*$IFACE" 2>/dev/null || true
pkill -f "dhclient.*$IFACE"       2>/dev/null || true
pkill -f "dhcpcd.*$IFACE"         2>/dev/null || true
sleep 1

# ─── Reset de interfaz ─────────────────────────────────────────────────────
log "Reset de interfaz..."
ip link set "$IFACE" down 2>/dev/null || true
sleep 2
ip addr flush dev "$IFACE" 2>/dev/null || true
ip route flush dev "$IFACE" 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
sleep 1

rfkill unblock wifi 2>/dev/null || true

ip link set "$IFACE" up 2>/dev/null || true
sleep 2

# ─── Recargar driver si la interfaz no responde ────────────────────────────
if ! iface_exists || [ "$(cat /sys/class/net/$IFACE/operstate 2>/dev/null)" = "down" ]; then
    warn "Interfaz caída."
    if [ "$DRIVER_RELOAD" = "yes" ]; then
        DRIVER=$(readlink -f "/sys/class/net/$IFACE/device/driver" 2>/dev/null | xargs basename 2>/dev/null || true)
        if [ -n "$DRIVER" ]; then
            warn "Recargando driver: $DRIVER"
            modprobe -r "$DRIVER" 2>/dev/null || true
            sleep 2
            modprobe "$DRIVER" 2>/dev/null || true
            sleep 3
            # re-detectar
            IFACE=""
            for _dev in /sys/class/net/*/wireless; do
                [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
            done
            [ -z "$IFACE" ] && die "Interfaz desapareció tras recargar driver."
            log "Nueva interfaz: $IFACE"
            ip link set "$IFACE" up 2>/dev/null || true
            sleep 2
        fi
    fi
fi

# ─── Borrar perfiles NM en modo ad-hoc / IBSS ──────────────────────────────
log "Eliminando perfiles NM residuales de ad-hoc..."
while IFS= read -r con_uuid; do
    [ -z "$con_uuid" ] && continue
    con_name=$(nmcli -t -f connection.id connection show "$con_uuid" 2>/dev/null || true)
    log "  Borrando perfil ad-hoc: ${con_name:-$con_uuid}"
    nmcli connection delete "$con_uuid" 2>/dev/null || true
done < <(nmcli -t -f UUID,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$2 == "802-11-wireless" {print $1}')

# También buscar inactivos con mode=adhoc
while IFS= read -r con_uuid; do
    [ -z "$con_uuid" ] && continue
    mode=$(nmcli -t -f 802-11-wireless.mode connection show "$con_uuid" 2>/dev/null || true)
    if [ "$mode" = "adhoc" ] || [ "$mode" = "1" ]; then
        con_name=$(nmcli -t -f connection.id connection show "$con_uuid" 2>/dev/null || true)
        log "  Borrando perfil inactivo ad-hoc: ${con_name:-$con_uuid}"
        nmcli connection delete "$con_uuid" 2>/dev/null || true
    fi
done < <(nmcli -t -f UUID connection show 2>/dev/null)

# ─── Recargar configuración de NM ──────────────────────────────────────────
log "Recargando configuración NM..."
nmcli connection reload 2>/dev/null || true
nmcli general reload 2>/dev/null || true
sleep 1

# ─── Devolver a NM con ciclo limpio ────────────────────────────────────────
log "Entregando $IFACE a NetworkManager..."
nmcli device set "$IFACE" managed yes 2>/dev/null || true
sleep 3

# Si NM sigue sin verlo, reiniciar servicio
if ! nmcli -t -f DEVICE device show "$IFACE" &>/dev/null; then
    warn "NM no ve $IFACE. Reiniciando servicio..."
    systemctl restart NetworkManager
    sleep 4
fi

# Esperar a que el dispositivo aparezca como disconnected
log "Esperando estado 'disconnected'..."
if ! wait_for_state disconnected "$TIMEOUT_NM"; then
    warn "Estado actual: $(nm_state)"
    warn "Forzando ciclo managed no/yes..."
    nmcli device set "$IFACE" managed no 2>/dev/null || true
    sleep 2
    nmcli device set "$IFACE" managed yes 2>/dev/null || true
    sleep 3
fi

# ─── Función de reconexión con timeout explícito ───────────────────────────
attempt_reconnect() {
    log "Intento de reconexión..."

    # 1) Por SSID guardado (más robusto que nombre de perfil)
    if [ -n "$SAVED_SSID" ]; then
        log "Conectando por SSID: '$SAVED_SSID'"
        timeout 20 nmcli device wifi connect "$SAVED_SSID" ifname "$IFACE" --wait 20 2>/dev/null && return 0
        warn "Falló conexión por SSID."
    fi

    # 2) Por nombre de perfil guardado
    if [ -n "$SAVED_CON" ]; then
        log "Activando perfil: '$SAVED_CON'"
        timeout 20 nmcli connection up "$SAVED_CON" --wait 20 2>/dev/null && return 0
        warn "Falló activación de perfil."
    fi

    # 3) Auto-conexión genérica del dispositivo
    log "Intentando auto-conexión..."
    timeout 20 nmcli device connect "$IFACE" --wait 20 2>/dev/null && return 0

    return 1
}

# ─── Reconectar ────────────────────────────────────────────────────────────
if attempt_reconnect; then
    log "Conexión iniciada. Esperando 'activated'..."
else
    warn "No se pudo iniciar conexión automáticamente."
fi

# Polling de estado con timeout
waited=0
while [ "$waited" -lt "$TIMEOUT_CONN" ]; do
    if is_connected; then
        log "=== CONECTADO ==="
        break
    fi
    # Si NM se atascó en "configuring", reiniciar intento
    local_st=$(nm_state)
    if [ "$local_st" = "configuring" ] || [ "$local_st" = "50" ]; then
        if [ "$((waited % 10))" -eq 9 ]; then
            warn "NM atascado en 'configuring'. Reintentando..."
            nmcli device disconnect "$IFACE" 2>/dev/null || true
            sleep 2
            attempt_reconnect || true
        fi
    fi
    sleep 1
    waited=$((waited + 1))
done

# ─── Si sigue sin conectar, diagnóstico y fallback ─────────────────────────
if ! is_connected; then
    warn "Sin conexión tras ${TIMEOUT_CONN}s. Estado: $(nm_state)"
    echo ""
    log "Diagnóstico:"
    nmcli device show "$IFACE" 2>/dev/null | grep -E "GENERAL\.|IP4\.|IP6\.|WIRED-PROPERTIES" || true
    echo ""
    log "Redes disponibles:"
    nmcli -t -f SSID,SIGNAL,SECURITY,ACTIVE dev wifi list ifname "$IFACE" 2>/dev/null | grep -v '^:' | head -12 || true
    echo ""
    log "Últimos logs de NetworkManager:"
    journalctl -u NetworkManager --no-pager -n 15 2>/dev/null || true
    echo ""
    warn "Reconexión manual:"
    warn "  nmcli device wifi list"
    warn "  nmcli device wifi connect '<SSID>' --ask"
fi

# ─── Limpiar temporales ────────────────────────────────────────────────────
rm -f /tmp/adhoc/my_ip /tmp/adhoc/cell_id /tmp/adhoc/nm_saved_connection /tmp/adhoc-master.flag

echo ""
log "=== RESUMEN ==="
nmcli device status | grep -E "DEVICE|$IFACE" || true
echo ""
