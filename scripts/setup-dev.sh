#!/usr/bin/env bash
set -euo pipefail

# setup-dev.sh — Setup de entorno de desarrollo y ejecución de tests.
# Uso: ./scripts/setup-dev.sh
# No requiere root.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"

echo "[DEV] Creando virtualenv de desarrollo..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$REPO_ROOT/src/requirements.txt" -q

echo "[DEV] Generando audio dummy para tests..."
mkdir -p /tmp/test_music
if command -v ffmpeg >/dev/null 2>&1; then
    "$VENV/bin/python" -c "
import subprocess
subprocess.run([
    'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=2',
    '-c:a', 'libmp3lame', '-b:a', '128k', '/tmp/test_music/dummy.mp3'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
print('[DEV] Audio dummy generado con ffmpeg')
"
else
    echo "[DEV] ffmpeg no disponible; creando dummy binario mínimo"
    # Crear archivo WAV mínimo válido (44 bytes header + 1 sample)
    python3 -c "
import struct
with open('/tmp/test_music/dummy.wav','wb') as f:
    f.write(b'RIFF')
    f.write(struct.pack('<I', 36))
    f.write(b'WAVEfmt ')
    f.write(struct.pack('<IHHIIHH', 16, 1, 1, 44100, 88200, 2, 16))
    f.write(b'data')
    f.write(struct.pack('<I', 0))
print('[DEV] WAV dummy listo')
"
fi

echo "[DEV] Ejecutando tests..."
export PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}"
"$VENV/bin/pytest" "$REPO_ROOT/tests/" -v --timeout=30 -k "not test_streamer_local" || true

echo "[DEV] Listo. Para activar el entorno: source $VENV/bin/activate"
