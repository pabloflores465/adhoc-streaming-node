#!/usr/bin/env bash
# network-setup.sh — Llamado por el daemon systemd (init-node.sh).
# Para uso manual usa adhoc-on.sh / adhoc-off.sh.
set -euo pipefail

IFACE="${ADHOC_IFACE:-wlan0}"
SSID="${ADHOC_SSID:-ADHOC-STREAM}"
FREQ="${ADHOC_FREQ:-2412}"
IP_PREFIX="${ADHOC_NET:-192.168.99}"
PREFERRED_CELL="${PREFERRED_CELL:-}"

mkdir -p /tmp/adhoc

# IP fija derivada de machine-id
MACHINE_ID=$(cat /etc/machine-id)
HEX_BYTE=${MACHINE_ID:0:2}
DEC=$((16#$HEX_BYTE))
LAST_OCTET=$(( (DEC % 240) + 10 ))
FIXED_IP="${IP_PREFIX}.${LAST_OCTET}"

echo "[NET] Configurando $IFACE (IP fija: $FIXED_IP)..."

# Liberar de NM (runtime, sin archivo permanente)
nmcli device set "$IFACE" managed no 2>/dev/null || true
nmcli device disconnect "$IFACE" 2>/dev/null || true
sleep 1

# Limpiar estado anterior
ip link set "$IFACE" down 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true
iw dev "$IFACE" ibss leave 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip link set "$IFACE" up

_assign_ip_and_exit() {
    local cell_id="$1"
    local is_master="${2:-0}"
    if ! ip addr show dev "$IFACE" | grep -q "${FIXED_IP}/24"; then
        ip addr add "${FIXED_IP}/24" dev "$IFACE"
    fi
    echo "$FIXED_IP" > /tmp/adhoc/my_ip
    echo "$cell_id" > /tmp/adhoc/cell_id
    if [ "$is_master" = "1" ]; then
        touch /tmp/adhoc-master.flag
    else
        rm -f /tmp/adhoc-master.flag
    fi
    echo "[NET] Configuración finalizada. IP: $FIXED_IP"
    ip addr show "$IFACE"
    exit 0
}

_join_ibss() {
    local cell="$1" freq="$2"
    ip link set "$IFACE" down
    iw dev "$IFACE" set type ibss
    ip link set "$IFACE" up
    iw dev "$IFACE" ibss join "$SSID" "$freq" fixed-freq "$cell"
}

# === Reintento a celda preferida ===
if [ -n "$PREFERRED_CELL" ]; then
    echo "[NET] Intentando celda preferida: $PREFERRED_CELL"
    iw dev "$IFACE" scan ap-force 2>/dev/null || iw dev "$IFACE" scan 2>/dev/null || true
    sleep 4
    FOUND=$(iw dev "$IFACE" scan dump 2>/dev/null | awk -v ssid="$SSID" -v cell="$PREFERRED_CELL" '
        /^BSS /    { bssid=$2; gsub(/\(on .+\)/, "", bssid); freq=""; signal="" }
        /^\tfreq:/    { freq=$2 }
        /^\tsignal:/  { signal=$2 }
        /^\tSSID:/    { if ($2 == ssid && bssid == cell) print freq, signal }
    ' || true)
    if [ -n "$FOUND" ]; then
        pref_freq=$(awk '{print $1}' <<< "$FOUND")
        pref_signal=$(awk '{print $2}' <<< "$FOUND")
        echo "[NET] Celda preferida hallada @ ${pref_freq}MHz (${pref_signal} dBm)"
        _join_ibss "$PREFERRED_CELL" "$pref_freq"
        _assign_ip_and_exit "$PREFERRED_CELL" "0"
    else
        echo "[NET] Celda preferida no encontrada. Continuando escaneo..."
    fi
fi

# === Escaneo normal ===
echo "[NET] Escaneando IBSS con SSID '$SSID' (espera 4s)..."
iw dev "$IFACE" scan ap-force 2>/dev/null || iw dev "$IFACE" scan 2>/dev/null || true
sleep 4

SCAN_RESULTS=$(iw dev "$IFACE" scan dump 2>/dev/null | awk -v ssid="$SSID" '
    /^BSS /   { bssid=$2; gsub(/\(on .+\)/, "", bssid); freq=""; signal="" }
    /^\tfreq:/   { freq=$2 }
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
    echo "[NET] Encontrada: $bssid @ ${freq}MHz (${signal} dBm)"
    if [ "$sig_int" -gt "$BEST_SIGNAL" ]; then
        BEST_SIGNAL=$sig_int
        BEST_BSSID=$bssid
        BEST_FREQ=$freq
    fi
done <<< "$SCAN_RESULTS"

if [ -n "$BEST_BSSID" ]; then
    echo "[NET] Uniendo a mejor red: $BEST_BSSID (${BEST_SIGNAL} dBm)"
    _join_ibss "$BEST_BSSID" "$BEST_FREQ"
    _assign_ip_and_exit "$BEST_BSSID" "0"
else
    echo "[NET] Sin redes en rango. Creando IBSS propia..."
    RAND_MAC=$(printf '02:%02x:%02x:%02x:%02x:%02x' \
        $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)) \
        $((RANDOM % 256)) $((RANDOM % 256)))
    _join_ibss "$RAND_MAC" "$FREQ"
    _assign_ip_and_exit "$RAND_MAC" "1"
fi
