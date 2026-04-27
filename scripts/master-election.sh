#!/usr/bin/env bash
set -euo pipefail

# master-election.sh — Decide si este nodo debe ser Master basado en recursos
# Devuelve "1" si es Master, "0" si no.

# Métricas: RAM libre (MB) + CPU cores * 1000 + carga invertida
RAM=$(free -m | awk '/^Mem:/ {print $7}')
CORES=$(nproc)
LOAD=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | tr -d ',')
SCORE=$(awk "BEGIN {printf \"%d\", $RAM + ($CORES * 1000) - ($LOAD * 500)}")

# Guardar score en tmp para que otros nodos lo vean por anuncio
mkdir -p /tmp/adhoc
printf '%s\t%s\t%d\n' "$(cat /etc/machine-id | cut -c1-8)" "$(hostname)" "$SCORE" > /tmp/adhoc/my-score

# Si ya existe flag de creador de red, es Master
if [ -f /tmp/adhoc-master.flag ]; then
    echo "1"
    exit 0
fi

# Si no hay flag, no somos creadores. El daemon Python hará consenso vía broadcast.
echo "0"
