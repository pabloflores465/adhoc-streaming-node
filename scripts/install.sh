#!/usr/bin/env bash
set -euo pipefail

# install.sh — Instalación declarativa del nodo AD-HOC Streaming.
# Uso: sudo ./scripts/install.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_ROOT="/opt/adhoc-node"
VENV="$INSTALL_ROOT/venv"

# ─── 1. Dependencias del sistema ─────────────────────────────────────────────
# Leidas de packages.json declarativo
SYSTEM_PACKAGES=(
    iw wireless-tools wpasupplicant
    python3 python3-pip python3-venv
    ffmpeg ffplay mpv
    htop iperf3
)

echo "[+] Instalando dependencias del sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq "${SYSTEM_PACKAGES[@]}"

# ─── 2. Entorno Python declarativo ───────────────────────────────────────────
echo "[+] Creando virtualenv en $VENV..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip setuptools wheel -q
"$VENV/bin/pip" install -r "$REPO_ROOT/src/requirements.txt" -q

# ─── 3. Instalación del código ───────────────────────────────────────────────
echo "[+] Instalando repositorio..."
mkdir -p "$INSTALL_ROOT"/{repo,music,logs}
rsync -a --delete \
    --exclude='.git' \
    --exclude='docs/figures' \
    --exclude='__pycache__' \
    "$REPO_ROOT/" "$INSTALL_ROOT/repo/"

# ─── 4. Descarga de música ───────────────────────────────────────────────────
echo "[+] Descargando/generando 25 canciones (max 90s)..."
bash "$INSTALL_ROOT/repo/scripts/download-music.sh" "$INSTALL_ROOT/music"

# ─── 5. Servicios systemd ────────────────────────────────────────────────────
echo "[+] Registrando servicios systemd..."
cp "$INSTALL_ROOT/repo/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable adhoc-node.service

# ─── 6. Permisos ─────────────────────────────────────────────────────────────
chmod -R 755 "$INSTALL_ROOT/repo/scripts/"*.sh
touch "$INSTALL_ROOT/logs/daemon.log"
touch "$INSTALL_ROOT/logs/network.log"

echo "[+] Instalación completa."
echo "    Logs:   $INSTALL_ROOT/logs/"
echo "    Música: $INSTALL_ROOT/music/"
echo "    Venv:   $VENV/"
echo ""
echo "    Arrancar:  sudo systemctl start adhoc-node.service"
echo "    Ver logs:  sudo journalctl -u adhoc-node.service -f"
echo "    Dashboard: http://<ip-nodo>:8080"
