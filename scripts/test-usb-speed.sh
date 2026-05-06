#!/usr/bin/env bash
# Prueba NO destructiva de velocidad usando un archivo temporal en tu HOME.
# Uso: ./test-usb-speed.sh [MB]
# Ejemplo: ./test-usb-speed.sh 256
set -euo pipefail

SIZE_MB="${1:-1024}"
TEST_FILE="${HOME}/usb-speed-test.tmp"

cleanup() {
    rm -f "$TEST_FILE"
}
trap cleanup EXIT

echo "=== Prueba NO destructiva de escritura/lectura ==="
echo "Archivo temporal : $TEST_FILE"
echo "Tamaño           : ${SIZE_MB} MB"
echo "Filesystem       : $(df -h "$HOME" | awk 'NR==2 {print $1 " montado en " $6 " (uso " $5 ")"}')"
echo

echo "[1/4] Estado inicial de memoria/I/O:"
free -h
vmstat 1 3

echo
echo "[2/4] ESCRITURA directa..."
sync
dd if=/dev/zero of="$TEST_FILE" bs=1M count="$SIZE_MB" oflag=direct status=progress
sync

echo
echo "[3/4] LECTURA directa..."
dd if="$TEST_FILE" of=/dev/null bs=1M iflag=direct status=progress

echo
echo "[4/4] Estado final de I/O:"
vmstat 1 3

rm -f "$TEST_FILE"
trap - EXIT

echo
echo "=== Prueba terminada; archivo temporal eliminado ==="
echo "Guía rápida: escritura <20 MB/s suele sentirse lenta para usar Fedora desde USB."
