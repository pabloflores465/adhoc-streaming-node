#!/usr/bin/env bash
set -euo pipefail

# install-fedora.sh — Instalación declarativa del nodo AD-HOC Streaming en Fedora.
# Optimizado para Fedora 43 KDE (NetworkManager + dnf5).
# Uso: sudo ./scripts/install-fedora.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_ROOT="/opt/adhoc-node"
VENV="$INSTALL_ROOT/venv"
# Detectar interfaz inalámbrica automáticamente (no requiere iw instalado)
IFACE="${ADHOC_IFACE:-}"
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi
if [ -z "$IFACE" ]; then
    echo "[!] No se detectó interfaz inalámbrica. Especifica: sudo ADHOC_IFACE=wlanX ./install-fedora.sh"
    exit 1
fi
echo "[+] Interfaz inalámbrica detectada: $IFACE"

# ─── 0. Detectar versión de Fedora ─────────────────────────────────────────
FEDORA_VERSION=$(rpm -E %fedora)
echo "[+] Detectado Fedora $FEDORA_VERSION"

# ─── 1. Habilitar rpmfusion-free (ffmpeg completo con libmp3lame) ──────────
if ! rpm -qa | grep -q rpmfusion-free-release; then
    echo "[+] Habilitando repositorio rpmfusion-free..."
    dnf install -y "https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VERSION}.noarch.rpm"
fi

# ─── 2. Excluir interfaz Wi-Fi de NetworkManager (KDE/Plasma) ──────────────
# Fedora KDE usa NetworkManager por defecto. Si gestiona wlan0, entra en
# conflicto con nuestros scripts iw/ip para IBSS.
NM_UNMANAGED="/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf"
if [ ! -f "$NM_UNMANAGED" ]; then
    echo "[+] Configurando NetworkManager: ignorando $IFACE..."
    mkdir -p /etc/NetworkManager/conf.d
    cat > "$NM_UNMANAGED" <<EOF
# Generado por adhoc-streaming-node install-fedora.sh
# Evita que NetworkManager gestione la interfaz usada para IBSS.
[device-$IFACE]
match-device=interface-name:$IFACE
managed=false
EOF
    # Recargar NetworkManager si está corriendo
    if systemctl is-active --quiet NetworkManager; then
        systemctl reload NetworkManager || systemctl restart NetworkManager
    fi
fi

# ─── 3. Dependencias del sistema ───────────────────────────────────────────
# Nota: wireless-tools omitido (obsoleto en Fedora; iw lo reemplaza).
SYSTEM_PACKAGES=(
    iw
    wpa_supplicant
    python3
    python3-pip
    ffmpeg
    mpv
    htop
    iperf3
    rsync
)

echo "[+] Instalando dependencias del sistema..."
dnf install -y "${SYSTEM_PACKAGES[@]}"

# ─── 4. Entorno Python declarativo ─────────────────────────────────────────
echo "[+] Creando virtualenv en $VENV..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip setuptools wheel -q
"$VENV/bin/pip" install -r "$REPO_ROOT/src/requirements.txt" -q

# ─── 5. Instalación del código ─────────────────────────────────────────────
echo "[+] Instalando repositorio..."
mkdir -p "$INSTALL_ROOT"/{repo,music,logs,state}
rsync -a --delete \
    --exclude='.git' \
    --exclude='docs/figures' \
    --exclude='__pycache__' \
    "$REPO_ROOT/" "$INSTALL_ROOT/repo/"

# ─── 6. Descarga de música ─────────────────────────────────────────────────
echo "[+] Descargando/generando 25 canciones (max 90s)..."
bash "$INSTALL_ROOT/repo/scripts/download-music.sh" "$INSTALL_ROOT/music"

# ─── 7. Servicios systemd ──────────────────────────────────────────────────
echo "[+] Registrando servicios systemd..."
cp "$INSTALL_ROOT/repo/systemd/"*.service /etc/systemd/system/
# Actualizar la interfaz real en el servicio instalado
sed -i "s/ADHOC_IFACE=wlan0/ADHOC_IFACE=${IFACE}/" /etc/systemd/system/adhoc-node.service
systemctl daemon-reload
systemctl enable adhoc-node.service

# ─── 8. SELinux (permitir que el daemon manipule red y escriba logs) ──────
if command -v setenforce >/dev/null 2>&1 && getenforce | grep -q Enforcing; then
    echo "[+] Configurando SELinux para el nodo AD-HOC..."
    # Permitir a procesos en /opt ejecutar operaciones de red
    semanage fcontext -a -t usr_t "$INSTALL_ROOT(/.*)?" 2>/dev/null || true
    restorecon -Rv "$INSTALL_ROOT" 2>/dev/null || true
    # Permitir que scripts bash manipulen interfaces (iw, ip)
    setsebool -P domain_can_mmap_files 1 2>/dev/null || true
fi

# ─── 9. Firewalld (puerto web + multicast UDP) ─────────────────────────────
if systemctl is-active --quiet firewalld; then
    echo "[+] Configurando firewalld..."
    firewall-cmd --permanent --add-port=8080/tcp
    firewall-cmd --permanent --add-port=5004/udp
    firewall-cmd --permanent --add-port=5005/udp
    # Permitir multicast en la zona activa
    firewall-cmd --permanent --direct --add-rule ipv4 filter INPUT 0 -d 239.255.42.42 -j ACCEPT 2>/dev/null || true
    firewall-cmd --reload
fi

# ─── 10. Permisos ──────────────────────────────────────────────────────────
chmod -R 755 "$INSTALL_ROOT/repo/scripts/"*.sh
touch "$INSTALL_ROOT/logs/daemon.log"
touch "$INSTALL_ROOT/logs/network.log"
touch "$INSTALL_ROOT/logs/node.log"

echo ""
echo "[+] Instalación completa en Fedora $FEDORA_VERSION."
echo "    Logs:   $INSTALL_ROOT/logs/"
echo "    Música: $INSTALL_ROOT/music/"
echo "    Venv:   $VENV/"
echo ""
echo "    NetworkManager: $IFACE marcado como unmanaged"
echo "    SELinux:        contexto aplicado a $INSTALL_ROOT"
echo "    Firewalld:      puertos 8080/tcp, 5004/udp, 5005/udp abiertos"
echo "    Arrancar:       sudo systemctl start adhoc-node.service"
echo "    Ver logs:       sudo journalctl -u adhoc-node.service -f"
echo "    Dashboard:      http://<ip-nodo>:8080"
