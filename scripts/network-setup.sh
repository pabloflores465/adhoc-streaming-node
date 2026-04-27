#!/usr/bin/env bash
set -euo pipefail

# network-setup.sh — IBSS con cell ID dinámico.
# Escanea redes AD-HOC con SSID dado, elige la de mejor señal y se une.
# Si no encuentra ninguna, genera cell ID aleatorio y crea red propia.
# Si PREFERRED_CELL está definida, intenta re-unirse a esa celda primero.

IFACE="${ADHOC_IFACE:-wlan0}"
SSID="${ADHOC_SSID:-ADHOC-STREAM}"
FREQ="${ADHOC_FREQ:-2412}"
IP_PREFIX="${ADHOC_NET:-192.168.99}"
PREFERRED_CELL="${PREFERRED_CELL:-}"

mkdir -p /tmp/adhoc

# Calcular IP fija derivada de los primeros 2 bytes de /etc/machine-id
MACHINE_ID=$(cat /etc/machine-id)
HEX_BYTE=${MACHINE_ID:0:2}
DEC=$((16#$HEX_BYTE))
LAST_OCTET=$(( (DEC % 240) + 10 ))
FIXED_IP="${IP_PREFIX}.${LAST_OCTET}"

echo "[NET] Configurando $IFACE (IP fija: $FIXED_IP)..."

ip link set "$IFACE" down 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true

ip link set "$IFACE" up

# === Reintento a celda preferida (estado previo) ===
if [ -n "$PREFERRED_CELL" ]; then
    echo "[NET] Reintentando celda preferida: $PREFERRED_CELL"
    # Escaneo breve
    iw dev "$IFACE" scan 2>/dev/null >/dev/null
    FOUND=$(iw dev "$IFACE" scan 2>/dev/null | awk -v ssid="$SSID" -v cell="$PREFERRED_CELL" '
        /^BSS / { bssid=$2; freq=""; signal=""; match_ssid=0 }
        /freq:/ { freq=$2 }
        /signal:/ { signal=$2 }
        /SSID: / {
            if ($2 == ssid) {
                gsub(/\(on .+\)/, "", bssid)
                if (bssid == cell) {
                    print freq, signal
                }
            }
        }
    ')
    if [ -n "$FOUND" ]; then
        read -r pref_freq pref_signal <<< "$FOUND"
        echo "[NET] Celda preferida encontrada @ ${pref_freq}MHz (${pref_signal} dBm). Uniendo..."
        iw dev "$IFACE" set type ibss
        ip link set "$IFACE" up
        iw dev "$IFACE" ibss join "$SSID" "$pref_freq" fixed-freq "$PREFERRED_CELL"
        ip addr add "${FIXED_IP}/24" dev "$IFACE"
        echo "$FIXED_IP" > /tmp/adhoc/my_ip
        echo "$PREFERRED_CELL" > /tmp/adhoc/cell_id
        rm -f /tmp/adhoc-master.flag
        echo "[NET] Re-unión a celda previa completada."
        ip addr show "$IFACE"
        exit 0
    else
        echo "[NET] Celda preferida no encontrada. Continuando con escaneo normal..."
    fi
fi

# === Escaneo normal ===
echo "[NET] Escaneando IBSS con SSID '$SSID'..."
SCAN_RESULTS=$(iw dev "$IFACE" scan 2>/dev/null | awk -v ssid="$SSID" '
    /^BSS / { bssid=$2; freq=""; signal=""; match_ssid=0 }
    /freq:/ { freq=$2 }
    /signal:/ { signal=$2 }
    /SSID: / {
        if ($2 == ssid) {
            gsub(/\(on .+\)/, "", bssid)
            print bssid, freq, signal
        }
    }
')

BEST_BSSID=""
BEST_FREQ=""
BEST_SIGNAL=-999

while read -r line; do
    [ -z "$line" ] && continue
    read -r bssid freq signal <<< "$line"
    # signal viene como -45.00 — convertir a entero para comparar
    sig_int=$(awk "BEGIN {printf \"%d\", $signal}")
    echo "[NET] Encontrada: $bssid @ ${freq}MHz (${signal} dBm)"
    if [ "$sig_int" -gt "$BEST_SIGNAL" ]; then
        BEST_SIGNAL=$sig_int
        BEST_BSSID=$bssid
        BEST_FREQ=$freq
    fi
done <<< "$SCAN_RESULTS"

if [ -n "$BEST_BSSID" ]; then
    echo "[NET] Uniendo a mejor red: $BEST_BSSID (${BEST_SIGNAL} dBm)"
    iw dev "$IFACE" set type ibss
    ip link set "$IFACE" up
    iw dev "$IFACE" ibss join "$SSID" "$BEST_FREQ" fixed-freq "$BEST_BSSID"
    ip addr add "${FIXED_IP}/24" dev "$IFACE"
    echo "$FIXED_IP" > /tmp/adhoc/my_ip
    echo "$BEST_BSSID" > /tmp/adhoc/cell_id
    rm -f /tmp/adhoc-master.flag
else
    echo "[NET] Sin redes en rango. Creando IBSS propia..."
    # Generar MAC local aleatoria (locally administered)
    RAND_MAC=$(printf '02:%02x:%02x:%02x:%02x:%02x' \
        $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)) \
        $((RANDOM % 256)) $((RANDOM % 256)))
    iw dev "$IFACE" set type ibss
    ip link set "$IFACE" up
    iw dev "$IFACE" ibss join "$SSID" "$FREQ" fixed-freq "$RAND_MAC"
    ip addr add "${FIXED_IP}/24" dev "$IFACE"
    echo "$FIXED_IP" > /tmp/adhoc/my_ip
    touch /tmp/adhoc-master.flag
    echo "$RAND_MAC" > /tmp/adhoc/cell_id
fi

echo "[NET] Configuración finalizada."
ip addr show "$IFACE"
cat /tmp/adhoc/cell_id
