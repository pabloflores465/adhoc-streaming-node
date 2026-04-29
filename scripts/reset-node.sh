#!/usr/bin/env bash
# reset-node.sh — Limpieza total. Borra todo lo que instaló este proyecto.
# El sistema queda como si nunca se hubiera instalado nada.
# Uso: sudo bash scripts/reset-node.sh
set -uo pipefail

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

ok()   { echo -e "${GRN}[OK]${NC}  $*"; }
warn() { echo -e "${YEL}[--]${NC}  $*"; }
info() { echo -e "      $*"; }

# ─── Root check ────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[!] Ejecutar como root: sudo bash scripts/reset-node.sh${NC}"
    exit 1
fi

echo ""
echo -e "${RED}╔══════════════════════════════════════════════════════╗"
echo -e "║           RESET TOTAL — adhoc-streaming-node         ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Esto elimina:"
echo "  • Servicio systemd adhoc-node"
echo "  • Directorio /opt/adhoc-node  (venv, música, logs, estado)"
echo "  • Config NetworkManager 99-adhoc-unmanaged.conf"
echo "  • Reglas de firewalld añadidas por el proyecto"
echo "  • Contextos SELinux de /opt/adhoc-node"
echo "  • Archivos temporales /tmp/adhoc*"
echo "  • Paquetes instalados exclusivamente por este proyecto"
echo "    (ffmpeg, mpv, iperf3 — iw/python3/rsync se conservan)"
echo ""
read -rp "  ¿Continuar? [s/N] " CONFIRM
[[ "$CONFIRM" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }
echo ""

# ─── Auto-detectar interfaz inalámbrica ────────────────────────────────────
IFACE="${ADHOC_IFACE:-}"
if [ -z "$IFACE" ]; then
    for _dev in /sys/class/net/*/wireless; do
        [ -d "$_dev" ] && IFACE=$(basename "$(dirname "$_dev")") && break
    done
fi

# ─── 1. Detener y deshabilitar el servicio systemd ─────────────────────────
echo "── 1. Servicio systemd"
if systemctl is-active --quiet adhoc-node.service 2>/dev/null; then
    systemctl stop adhoc-node.service && ok "adhoc-node.service detenido" || warn "No se pudo detener el servicio"
else
    warn "adhoc-node.service no estaba activo"
fi

if systemctl is-enabled --quiet adhoc-node.service 2>/dev/null; then
    systemctl disable adhoc-node.service && ok "adhoc-node.service deshabilitado" || warn "No se pudo deshabilitar"
else
    warn "adhoc-node.service no estaba habilitado"
fi

SERVICE_FILE="/etc/systemd/system/adhoc-node.service"
if [ -f "$SERVICE_FILE" ]; then
    rm -f "$SERVICE_FILE" && ok "Eliminado $SERVICE_FILE"
else
    warn "No existe $SERVICE_FILE"
fi

systemctl daemon-reload
ok "daemon-reload ejecutado"

# ─── 2. Restaurar interfaz WiFi ────────────────────────────────────────────
echo ""
echo "── 2. Interfaz WiFi"
if [ -n "$IFACE" ]; then
    iw dev "$IFACE" ibss leave 2>/dev/null && ok "Salido de red IBSS en $IFACE" || warn "No estaba en IBSS o ya limpio"
    ip link set "$IFACE" down 2>/dev/null || true
    ip addr flush dev "$IFACE" 2>/dev/null || true
    iw dev "$IFACE" set type managed 2>/dev/null && ok "$IFACE reseteado a modo managed" || warn "No se pudo resetear modo (puede ser normal)"
    ip link set "$IFACE" up 2>/dev/null || true
else
    warn "No se detectó interfaz inalámbrica — skip"
fi

# ─── 3. NetworkManager ─────────────────────────────────────────────────────
echo ""
echo "── 3. NetworkManager"
NM_CONF="/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf"
if [ -f "$NM_CONF" ]; then
    rm -f "$NM_CONF" && ok "Eliminado $NM_CONF"
else
    warn "No existe $NM_CONF"
fi

if [ -n "$IFACE" ]; then
    nmcli device set "$IFACE" managed yes 2>/dev/null && ok "$IFACE devuelto a NM" || warn "nmcli: no se pudo marcar managed"
fi

systemctl restart NetworkManager && ok "NetworkManager reiniciado" || warn "No se pudo reiniciar NM"
sleep 2

# ─── 4. Firewalld ──────────────────────────────────────────────────────────
echo ""
echo "── 4. Firewalld"
if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --permanent --remove-port=8080/tcp  2>/dev/null && ok "Puerto 8080/tcp eliminado"  || warn "8080/tcp no estaba o ya eliminado"
    firewall-cmd --permanent --remove-port=5004/udp  2>/dev/null && ok "Puerto 5004/udp eliminado"  || warn "5004/udp no estaba o ya eliminado"
    firewall-cmd --permanent --remove-port=5005/udp  2>/dev/null && ok "Puerto 5005/udp eliminado"  || warn "5005/udp no estaba o ya eliminado"
    firewall-cmd --permanent --direct --remove-rule ipv4 filter INPUT 0 \
        -d 239.255.42.42 -j ACCEPT 2>/dev/null && ok "Regla multicast eliminada" || warn "Regla multicast no existía"
    firewall-cmd --reload 2>/dev/null && ok "firewalld recargado" || warn "No se pudo recargar firewalld"
else
    warn "firewalld no está activo — skip"
fi

# ─── 5. SELinux ────────────────────────────────────────────────────────────
echo ""
echo "── 5. SELinux"
if command -v semanage >/dev/null 2>&1; then
    semanage fcontext -d "/opt/adhoc-node(/.*)?" 2>/dev/null && ok "Contexto SELinux eliminado" || warn "Contexto SELinux no existía"
else
    warn "semanage no disponible — skip"
fi

# ─── 6. Directorio de instalación /opt/adhoc-node ──────────────────────────
echo ""
echo "── 6. /opt/adhoc-node"
if [ -d /opt/adhoc-node ]; then
    rm -rf /opt/adhoc-node && ok "Eliminado /opt/adhoc-node"
else
    warn "No existe /opt/adhoc-node"
fi

# ─── 7. Archivos temporales ────────────────────────────────────────────────
echo ""
echo "── 7. Temporales"
rm -rf /tmp/adhoc  2>/dev/null && ok "Eliminado /tmp/adhoc"  || warn "/tmp/adhoc no existía"
rm -f  /tmp/adhoc-master.flag 2>/dev/null && ok "Eliminado /tmp/adhoc-master.flag" || warn "Flag master no existía"

# ─── 8. Paquetes del proyecto ──────────────────────────────────────────────
# Solo eliminamos los que son exclusivos del proyecto.
# iw, wpa_supplicant, python3, python3-pip, rsync se conservan (pueden ser usados por el SO).
echo ""
echo "── 8. Paquetes"
REMOVE_PKGS=(ffmpeg mpv iperf3)
for pkg in "${REMOVE_PKGS[@]}"; do
    if rpm -q "$pkg" >/dev/null 2>&1; then
        dnf remove -y "$pkg" >/dev/null 2>&1 && ok "Eliminado: $pkg" || warn "No se pudo eliminar: $pkg"
    else
        warn "No instalado: $pkg"
    fi
done
info "(iw, wpa_supplicant, python3, rsync conservados — pueden ser del SO)"

# ─── 9. rpmfusion (opcional, pregunta) ────────────────────────────────────
echo ""
echo "── 9. rpmfusion-free"
if rpm -q rpmfusion-free-release >/dev/null 2>&1; then
    read -rp "      ¿Eliminar también rpmfusion-free? Puede afectar otros paquetes. [s/N] " RM_RPM
    if [[ "$RM_RPM" =~ ^[sS]$ ]]; then
        dnf remove -y rpmfusion-free-release >/dev/null 2>&1 && ok "rpmfusion-free eliminado" || warn "No se pudo eliminar rpmfusion-free"
    else
        warn "rpmfusion-free conservado"
    fi
else
    warn "rpmfusion-free no estaba instalado"
fi

# ─── Resumen final ─────────────────────────────────────────────────────────
echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════════╗"
echo -e "║                   RESET COMPLETADO                  ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  El sistema está limpio. Para empezar de nuevo:"
echo ""
echo "    sudo bash scripts/install-fedora.sh"
echo ""

if [ -n "$IFACE" ]; then
    echo "  Estado actual de $IFACE:"
    nmcli device status | grep -E "DEVICE|$IFACE" 2>/dev/null || true
fi
echo ""
