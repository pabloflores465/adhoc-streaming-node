#!/usr/bin/env bash
# adhoc-on.sh — Activa la red AD-HOC de streaming. Ejecutar como root.
# Uso: sudo ./scripts/adhoc-on.sh
# Para restaurar internet: sudo ./scripts/adhoc-off.sh
set -euo pipefail

IFACE="${ADHOC_IFACE:-}"
SSID="${ADHOC_SSID:-ADHOC-STREAM}"
FREQ="${ADHOC_FREQ:-2412}"
IP_PREFIX="${ADHOC_NET:-192.168.99}"

# ─── Auto-detectar interfaz inalámbrica ────────────────────────────────────
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
if [ -z "$IFACE" ]; then
    echo "[!] No se detectó interfaz inalámbrica. Especifica: sudo ADHOC_IFACE=wlanX ./adhoc-on.sh"
    exit 1
fi
echo "[ON] Interfaz: $IFACE | SSID: $SSID | Freq: ${FREQ}MHz"

# ─── IP fija derivada de machine-id ────────────────────────────────────────
MACHINE_ID=$(cat /etc/machine-id)
HEX_BYTE=${MACHINE_ID:0:2}
DEC=$((16#$HEX_BYTE))
LAST_OCTET=$(( (DEC % 240) + 10 ))
FIXED_IP="${IP_PREFIX}.${LAST_OCTET}"

mkdir -p /tmp/adhoc

# ─── Guardar conexión activa para restaurar después ────────────────────────
CURRENT_CON=$(nmcli -t -f NAME,DEVICE con show --active 2>/dev/null \
    | grep ":${IFACE}$" | cut -d: -f1 || true)
printf '%s' "${CURRENT_CON}" > /tmp/adhoc/nm_saved_connection
echo "[ON] Conexión NM guardada: '${CURRENT_CON:-ninguna}'"

# ─── Liberar interfaz de NetworkManager (solo en RAM, sin archivo conf.d) ──
echo "[ON] Liberando $IFACE de NetworkManager..."
nmcli device set "$IFACE" managed no 2>/dev/null || true
nmcli device disconnect "$IFACE" 2>/dev/null || true
sleep 1

# ─── Limpiar estado anterior ────────────────────────────────────────────────
ip link set "$IFACE" down 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true
iw dev "$IFACE" ibss leave 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip link set "$IFACE" up

# ─── Escanear redes AD-HOC existentes ──────────────────────────────────────
echo "[ON] Escaneando redes '$SSID' (espera 4s)..."
iw dev "$IFACE" scan ap-force 2>/dev/null || iw dev "$IFACE" scan 2>/dev/null || true
sleep 4

SCAN_RESULTS=$(iw dev "$IFACE" scan dump 2>/dev/null | awk -v ssid="$SSID" '
    /^BSS /   { bssid=$2; gsub(/\(on .+\)/, "", bssid); freq=""; signal="" }
    /^\tfreq:/   { freq=int($2) }
    /^\tsignal:/ { signal=$2 }
    /^\tSSID:/   { if ($2 == ssid && bssid != "" && freq != "" && signal != "") print bssid, freq, signal }
' || true)

BEST_BSSID=""
BEST_FREQ="$FREQ"
BEST_SIGNAL=-999

while IFS= read -r line; do
    [ -z "$line" ] && continue
    bssid=$(awk '{print $1}' <<< "$line")
    freq=$(awk '{print $2}' <<< "$line")
    signal=$(awk '{print $3}' <<< "$line")
    sig_int=$(awk "BEGIN {printf \"%d\", ($signal+0)}" 2>/dev/null || echo "-999")
    echo "[ON] Encontrada: $bssid @ ${freq}MHz (${signal} dBm)"
    if [ "$sig_int" -gt "$BEST_SIGNAL" ]; then
        BEST_SIGNAL=$sig_int
        BEST_BSSID=$bssid
        BEST_FREQ=$freq
    fi
done <<< "$SCAN_RESULTS"

# ─── Cambiar a modo IBSS ────────────────────────────────────────────────────
ip link set "$IFACE" down
iw dev "$IFACE" set type ibss
ip link set "$IFACE" up

if [ -n "$BEST_BSSID" ]; then
    echo "[ON] Uniéndose a red existente: $BEST_BSSID @ ${BEST_FREQ}MHz (${BEST_SIGNAL} dBm)"
    iw dev "$IFACE" ibss join "$SSID" "$BEST_FREQ" fixed-freq "$BEST_BSSID"
    echo "$BEST_BSSID" > /tmp/adhoc/cell_id
    rm -f /tmp/adhoc-master.flag
else
    echo "[ON] Sin redes en rango. Creando nueva red AD-HOC..."
    RAND_MAC=$(printf '02:%02x:%02x:%02x:%02x:%02x' \
        $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)) \
        $((RANDOM % 256)) $((RANDOM % 256)))
    iw dev "$IFACE" ibss join "$SSID" "$FREQ" fixed-freq "$RAND_MAC"
    echo "$RAND_MAC" > /tmp/adhoc/cell_id
    touch /tmp/adhoc-master.flag
    echo "[ON] Soy el primero — posible Master."
fi

# ─── Asignar IP (sin fallar si ya existe) ──────────────────────────────────
if ip addr show dev "$IFACE" | grep -q "${FIXED_IP}/24"; then
    echo "[ON] IP ${FIXED_IP} ya asignada."
else
    ip addr add "${FIXED_IP}/24" dev "$IFACE"
fi
echo "$FIXED_IP" > /tmp/adhoc/my_ip

echo ""
echo "[ON] === AD-HOC ACTIVO ==="
echo "     Interfaz : $IFACE"
echo "     SSID     : $SSID"
echo "     IP local : $FIXED_IP"
echo "     Cell ID  : $(cat /tmp/adhoc/cell_id)"
echo "     Para apagar: sudo $(dirname "$0")/adhoc-off.sh"
echo ""
ip addr show "$IFACE"

# Arrancar el daemon si está instalado
if systemctl list-unit-files adhoc-node.service &>/dev/null; then
    echo "[ON] Arrancando adhoc-node.service..."
    systemctl start adhoc-node.service && echo "[ON] Daemon arrancado. Dashboard: http://${FIXED_IP}:8080" \
        || echo "[ON] ADVERTENCIA: el daemon no arrancó. Revisa: journalctl -u adhoc-node.service"
else
    echo "[ON] (adhoc-node.service no instalado — omitiendo arranque de daemon)"
fi
