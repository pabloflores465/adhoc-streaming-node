#!/usr/bin/env bash
# Chequeo NO destructivo de la USB clonada /dev/sdb.
# Uso: sudo ./check-usb-sdb.sh
set -euo pipefail

DEV="${1:-/dev/sdb}"
BASE="$(basename "$DEV")"

if [ "${EUID}" -ne 0 ]; then
  echo "[!] Ejecuta con sudo: sudo $0 ${DEV}"
  exit 1
fi

if [ ! -b "$DEV" ]; then
  echo "[!] No existe $DEV"
  exit 1
fi

echo "=== Dispositivo ==="
lsblk -o NAME,MODEL,SERIAL,TRAN,TYPE,SIZE,FSTYPE,FSUSE%,MOUNTPOINTS "$DEV"
echo

echo "=== USB speed / firmware ==="
USB_PATH="$(udevadm info --query=path --name="$DEV" | grep -o 'usb[0-9]*/[0-9.-]*' | tail -1 | cut -d/ -f2 || true)"
if [ -n "$USB_PATH" ] && [ -d "/sys/bus/usb/devices/$USB_PATH" ]; then
  for f in product manufacturer serial speed bcdDevice; do
    [ -r "/sys/bus/usb/devices/$USB_PATH/$f" ] && printf '%-12s: ' "$f" && cat "/sys/bus/usb/devices/$USB_PATH/$f"
  done
else
  udevadm info --query=property --name="$DEV" | grep -E 'ID_MODEL=|ID_SERIAL=|ID_VENDOR=|ID_PATH='
fi
echo

echo "=== Errores kernel recientes ==="
journalctl -k -b --no-pager | grep -Ei "${BASE}|usb|reset|I/O error|Buffer I/O|fail|error" | tail -n 80 || true
echo

echo "=== SMART/health USB bridge ==="
for dtype in scsi sat auto; do
  echo "--- smartctl -d $dtype ---"
  smartctl -H -A -d "$dtype" "$DEV" 2>&1 | head -n 80 || true
  echo
 done

echo "=== Benchmark lectura NO destructivo ==="
if command -v hdparm >/dev/null; then
  hdparm -tT "$DEV" || true
fi
echo

echo "=== Lectura directa 1GiB NO destructiva ==="
dd if="$DEV" of=/dev/null bs=64M count=16 iflag=direct status=progress || true

echo

echo "[OK] Chequeo terminado. No se escribió nada en $DEV."
