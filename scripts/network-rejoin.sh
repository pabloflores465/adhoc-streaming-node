#!/usr/bin/env bash
set -euo pipefail

# network-rejoin.sh — Reescanea IBSS y migra a celda mejor si es necesario.
# Ejecutar periódicamente desde el daemon.

IFACE="${ADHOC_IFACE:-wlan0}"
SSID="${ADHOC_SSID:-ADHOC-STREAM}"
IP_PREFIX="${ADHOC_NET:-192.168.99}"
LOG="/opt/adhoc-node/logs/network.log"

echo "[$(date -Iseconds)] [REJOIN] Iniciando reescaneo..." >> "$LOG"

# Leer celda actual
CURRENT_CELL=""
if [ -f /tmp/adhoc/cell_id ]; then
    CURRENT_CELL=$(cat /tmp/adhoc/cell_id)
fi

if [ -z "$CURRENT_CELL" ]; then
    echo "[$(date -Iseconds)] [REJOIN] Sin celda actual, saltando." >> "$LOG"
    exit 0
fi

ip link set "$IFACE" up 2>/dev/null || true

# Escaneo activo + espera para obtener resultados frescos en modo IBSS
iw dev "$IFACE" scan ap-force 2>/dev/null || iw dev "$IFACE" scan 2>/dev/null || true
sleep 3

# Parsear resultados (freq convertida a entero para compatibilidad con ibss join)
SCAN_RESULTS=$(iw dev "$IFACE" scan dump 2>/dev/null | awk -v ssid="$SSID" '
    /^BSS /   { bssid=$2; gsub(/\(on .+\)/, "", bssid); freq=""; signal="" }
    /^\tfreq:/   { freq=int($2) }
    /^\tsignal:/ { signal=$2 }
    /^\tSSID:/   {
        if ($2 == ssid && bssid != "" && freq != "" && signal != "") {
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
    sig_int=$(awk "BEGIN {printf \"%d\", $signal}")
    if [ "$sig_int" -gt "$BEST_SIGNAL" ]; then
        BEST_SIGNAL=$sig_int
        BEST_BSSID=$bssid
        BEST_FREQ=$freq
    fi
done <<< "$SCAN_RESULTS"

if [ -z "$BEST_BSSID" ]; then
    echo "[$(date -Iseconds)] [REJOIN] Ninguna celda detectada." >> "$LOG"
    exit 0
fi

# Si la mejor es la misma en la que estamos, no hacer nada
if [ "$BEST_BSSID" = "$CURRENT_CELL" ]; then
    echo "[$(date -Iseconds)] [REJOIN] Mejor celda es la actual ($CURRENT_CELL, ${BEST_SIGNAL} dBm). Sin cambios." >> "$LOG"
    exit 0
fi

# Si la señal de la celda actual está por debajo de -75 y hay otra mejor, migrar
CURRENT_SIGNAL=-999
while read -r line; do
    [ -z "$line" ] && continue
    read -r bssid freq signal <<< "$line"
    if [ "$bssid" = "$CURRENT_CELL" ]; then
        CURRENT_SIGNAL=$(awk "BEGIN {printf \"%d\", $signal}")
        break
    fi
done <<< "$SCAN_RESULTS"

# Umbral: migrar si la nueva es al menos 10dBm mejor, o si actual está debajo de -70
MIGRATE=false
if [ "$CURRENT_SIGNAL" -lt -70 ] && [ "$BEST_SIGNAL" -gt "$CURRENT_SIGNAL" ]; then
    MIGRATE=true
elif [ $((BEST_SIGNAL - CURRENT_SIGNAL)) -ge 10 ]; then
    MIGRATE=true
fi

if [ "$MIGRATE" != "true" ]; then
    echo "[$(date -Iseconds)] [REJOIN] Celda actual suficiente (${CURRENT_SIGNAL} dBm). No migrar a ${BEST_BSSID} (${BEST_SIGNAL} dBm)." >> "$LOG"
    exit 0
fi

# === MIGRACIÓN ===
echo "[$(date -Iseconds)] [REJOIN] Migrando $CURRENT_CELL (${CURRENT_SIGNAL} dBm) -> $BEST_BSSID (${BEST_SIGNAL} dBm)" >> "$LOG"

# Leer IP fija (siempre usamos la misma IP, derivada de MAC)
FIXED_IP="${IP_PREFIX}.1"
if [ -f /tmp/adhoc/my_ip ]; then
    FIXED_IP=$(cat /tmp/adhoc/my_ip)
fi

ip link set "$IFACE" down 2>/dev/null || true
iw dev "$IFACE" ibss leave 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true

if ! iw dev "$IFACE" set type ibss 2>/dev/null; then
    echo "[$(date -Iseconds)] [REJOIN] ERROR: set type ibss falló. Abortando migración." >> "$LOG"
    exit 1
fi
ip link set "$IFACE" up 2>/dev/null || true

if ! iw dev "$IFACE" ibss join "$SSID" "$BEST_FREQ" fixed-freq "$BEST_BSSID" 2>/dev/null; then
    echo "[$(date -Iseconds)] [REJOIN] ERROR: ibss join falló. Abortando migración." >> "$LOG"
    exit 1
fi

if ! ip addr show dev "$IFACE" | grep -q "${FIXED_IP}/24"; then
    ip addr add "${FIXED_IP}/24" dev "$IFACE" 2>/dev/null || true
fi
echo "$BEST_BSSID" > /tmp/adhoc/cell_id
rm -f /tmp/adhoc-master.flag

echo "[$(date -Iseconds)] [REJOIN] Migración completada a $BEST_BSSID con IP $FIXED_IP" >> "$LOG"
