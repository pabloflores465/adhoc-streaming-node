#!/usr/bin/env bash
# init-node.sh — Entrypoint principal del nodo. Ejecutado por systemd.

REPO_ROOT="/opt/adhoc-node/repo"
PYTHON="/opt/adhoc-node/venv/bin/python3"
LOG="/opt/adhoc-node/logs/node.log"
STATE_FILE="/opt/adhoc-node/state/node-state.json"

export PYTHONUNBUFFERED=1
export NODE_ID
NODE_ID="$(cut -c1-8 /etc/machine-id)"

# Enviar a log Y a journal (para que journalctl muestre los errores reales)
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "[$(date -Iseconds)] [INIT] Nodo $NODE_ID arrancando..."

# Verificar dependencias mínimas
if [ ! -x "$PYTHON" ]; then
    echo "[INIT] ERROR: Python no encontrado en $PYTHON. Ejecuta install-fedora.sh primero."
    exit 1
fi

# Leer estado previo si existe y es reciente
PREFERRED_CELL=""
if [ -f "$STATE_FILE" ]; then
    PREFERRED_CELL=$("$PYTHON" -c "
import json, time
try:
    with open('$STATE_FILE') as f:
        d = json.load(f)
    print(d.get('cell_id', '') if time.time() - d.get('timestamp', 0) < 300 else '')
except Exception:
    print('')
" 2>/dev/null || true)
    [ -n "$PREFERRED_CELL" ] && echo "[INIT] Estado previo: celda $PREFERRED_CELL"
fi

# 1) Configurar red — no matar el daemon si falla (red puede no tener IBSS)
export PREFERRED_CELL
if ! bash "$REPO_ROOT/scripts/network-setup.sh"; then
    echo "[INIT] ADVERTENCIA: network-setup.sh falló. El daemon arrancará sin red AD-HOC."
fi

# 2) Evaluar si somos Master
IS_MASTER=$(bash "$REPO_ROOT/scripts/master-election.sh" 2>/dev/null || echo "0")
export IS_MASTER
echo "[INIT] IS_MASTER=$IS_MASTER"

# 3) Lanzar daemon principal Python
echo "[INIT] Lanzando node-daemon.py..."
exec "$PYTHON" "$REPO_ROOT/src/node/node-daemon.py"
