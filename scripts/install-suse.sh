#!/usr/bin/env bash
set -euo pipefail

# install-suse.sh — Instalación declarativa del nodo AD-HOC Streaming en openSUSE Tumbleweed.
# Uso: sudo ./scripts/install-suse.sh
# Nota: deja el daemon en modo MANUAL. Para arrancar: sudo ./scripts/start-node.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_ROOT="/opt/adhoc-node"
VENV="$INSTALL_ROOT/venv"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "[!] Ejecuta como root: sudo ./scripts/install-suse.sh" >&2
    exit 1
fi

if ! command -v zypper >/dev/null 2>&1; then
    echo "[!] Este instalador es para openSUSE Tumbleweed (requiere zypper)." >&2
    exit 1
fi

# Detectar interfaz inalámbrica automáticamente.
IFACE="${ADHOC_IFACE:-}"
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
if [ -z "$IFACE" ]; then
    echo "[!] No se detectó interfaz inalámbrica. Especifica: sudo ADHOC_IFACE=wlanX ./scripts/install-suse.sh"
    exit 1
fi
echo "[+] Interfaz inalámbrica detectada: $IFACE"

# ─── 1. Repositorios multimedia ─────────────────────────────────────────────
# openSUSE puede traer ffmpeg/codecs limitados. Packman provee codecs completos.
if ! zypper lr -u | grep -qi 'packman.*Tumbleweed'; then
    echo "[+] Agregando repositorio Packman para codecs multimedia..."
    zypper --non-interactive ar -cfp 90 \
        "https://ftp.gwdg.de/pub/linux/misc/packman/suse/openSUSE_Tumbleweed/" \
        packman || true
fi

echo "[+] Refrescando repositorios..."
zypper --non-interactive --gpg-auto-import-keys refresh

# ─── 2. Dependencias del sistema ────────────────────────────────────────────
SYSTEM_PACKAGES=(
    iw
    wireless-tools
    wpa_supplicant
    NetworkManager
    python3
    python3-pip
    python3-virtualenv
    python3-devel
    ffmpeg
    mpv
    yt-dlp
    htop
    iperf3
    rsync
    curl
    wget
    iproute2
    net-tools
    nftables
    iptables
)

echo "[+] Instalando dependencias del sistema..."
zypper --non-interactive install --no-recommends "${SYSTEM_PACKAGES[@]}"

# ─── 2b. Codecs de audio ────────────────────────────────────────────────────
AUDIO_CODEC_PACKAGES=(
    gstreamer-plugins-base
    gstreamer-plugins-good
    gstreamer-plugins-bad
    gstreamer-plugins-ugly
    gstreamer-libav
    lame
    flac
)

echo "[+] Instalando codecs de audio..."
zypper --non-interactive install --no-recommends "${AUDIO_CODEC_PACKAGES[@]}" || true

# Preferir paquetes multimedia de Packman si está disponible, sin fallar si no.
if zypper lr | grep -q '^.*packman'; then
    echo "[+] Priorizando codecs desde Packman (si aplica)..."
    zypper --non-interactive dup --from packman --allow-vendor-change \
        --replacefiles --no-recommends || true
fi

# ─── 3. Entorno Python ──────────────────────────────────────────────────────
echo "[+] Creando virtualenv en $VENV..."
mkdir -p "$INSTALL_ROOT"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip setuptools wheel -q
"$VENV/bin/pip" install -r "$REPO_ROOT/src/requirements.txt" -q

# ─── 4. Instalación del código ──────────────────────────────────────────────
echo "[+] Instalando repositorio..."
mkdir -p "$INSTALL_ROOT"/{repo,music,logs,state}
rsync -a --delete \
    --exclude='.git' \
    --exclude='docs/figures' \
    --exclude='__pycache__' \
    "$REPO_ROOT/" "$INSTALL_ROOT/repo/"

# ─── 5. Descarga de música ──────────────────────────────────────────────────
echo "[+] Actualizando yt-dlp a la última versión..."
yt-dlp -U || true

echo "[+] Descargando/generando 25 canciones..."
bash "$INSTALL_ROOT/repo/scripts/download-music.sh" "$INSTALL_ROOT/music"

# ─── 6. Servicio systemd ────────────────────────────────────────────────────
# Igual que Fedora: modo 100% manual. No registrar ni habilitar servicio aquí.
echo "[+] Saltando registro de systemd (modo manual)."
echo "    Si quieres usar systemd manual: sudo $SCRIPT_DIR/install-service.sh"

# ─── 7. Firewall ────────────────────────────────────────────────────────────
# En IBSS firewalld puede causar 'No route to host'. Para el proyecto aislado lo detenemos.
if systemctl list-unit-files firewalld.service >/dev/null 2>&1; then
    echo "[+] Desactivando firewalld para no bloquear peers AD-HOC..."
    systemctl disable --now firewalld 2>/dev/null || true
fi

# ─── 8. NetworkManager ──────────────────────────────────────────────────────
# No se apaga permanentemente; adhoc-on/off lo gestionan en runtime.
if systemctl list-unit-files NetworkManager.service >/dev/null 2>&1; then
    systemctl enable --now NetworkManager 2>/dev/null || true
fi

# ─── 9. Permisos y logs ─────────────────────────────────────────────────────
chmod -R 755 "$INSTALL_ROOT/repo/scripts/"*.sh
chmod +x "$INSTALL_ROOT/repo/scripts/"*.sh 2>/dev/null || true
touch "$INSTALL_ROOT/logs/daemon.log"
touch "$INSTALL_ROOT/logs/network.log"
touch "$INSTALL_ROOT/logs/node.log"

cat <<EOF

[+] Instalación completa en openSUSE Tumbleweed.
    Logs:      $INSTALL_ROOT/logs/
    Música:    $INSTALL_ROOT/music/
    Venv:      $VENV/
    Interfaz:  $IFACE
    Firewalld: desactivado para no bloquear peers AD-HOC

    Activar AD-HOC:      sudo $SCRIPT_DIR/adhoc-on.sh
    Restaurar internet:  sudo $SCRIPT_DIR/adhoc-off.sh
    Arrancar daemon:     sudo $SCRIPT_DIR/start-node.sh
    Instalar servicio:   sudo $SCRIPT_DIR/install-service.sh
    Ver logs:            sudo journalctl -u adhoc-node.service -f
    Dashboard:           http://<ip-nodo>:8080
EOF
