#!/usr/bin/env bash
set -euo pipefail

# init-node.sh — Entrypoint principal del nodo
# Se ejecuta como servicio systemd al boot

REPO_ROOT="/opt/adhoc-node/repo"
VENV="/opt/adhoc-node/venv/bin/python3"
LOG="/opt/adhoc-node/logs/node.log"
STATE_FILE="/opt/adhoc-node/state/node-state.json"

export PYTHONUNBUFFERED=1
export NODE_ID="$(cat /etc/machine-id | cut -c1-8)"

exec >>"$LOG" 2>&1

echo "[$(date -Iseconds)] [INIT] Nodo $NODE_ID arrancando..."

# Leer estado previo si existe y es reciente
PREFERRED_CELL=""
if [ -f "$STATE_FILE" ]; then
    PREFERRED_CELL=$("$VENV" -c "
import json, time, sys
try:
    with open('$STATE_FILE') as f:
        d = json.load(f)
    if time.time() - d.get('timestamp', 0) < 300:
        print(d.get('cell_id', ''))
    else:
        print('')
except Exception:
    print('')
")
    if [ -n "$PREFERRED_CELL" ]; then
        echo "[INIT] Estado previo encontrado. Intentando re-unirse a celda $PREFERRED_CELL"
    fi
fi

# 1) Configurar red (pasando cell_id preferida si existe)
export PREFERRED_CELL
bash "$REPO_ROOT/scripts/network-setup.sh"

# 2) Evaluar si somos Master (basado en recursos)
IS_MASTER=$(bash "$REPO_ROOT/scripts/master-election.sh")
export IS_MASTER

# 3) Lanzar daemon principal Python
exec "$VENV" "$REPO_ROOT/src/node/node-daemon.py"
