# Guía de despliegue — Red AD-HOC Streaming

Pasos completos desde cero para cada nodo.

---

## Requisitos previos

- Fedora 43 (KDE o cualquier variante) — puede ser instalado en USB booteable
- Acceso `sudo` / root
- Tarjeta WiFi con soporte IBSS (modo ad-hoc) — verificar con `iw list | grep "Supported interface modes" -A 10`
- Conexión a internet **solo durante la instalación**

---

## 1. Clonar el repositorio

```bash
git clone <URL-DEL-REPO> ~/adhoc-streaming-node
cd ~/adhoc-streaming-node
```

---

## 2. Instalar dependencias del sistema

Ejecutar **una sola vez** por nodo. No rompe el internet.

```bash
sudo bash scripts/install-fedora.sh
```

Qué hace:
- Habilita `rpmfusion-free` (para ffmpeg con mp3)
- Instala: `iw`, `wpa_supplicant`, `python3`, `ffmpeg`, `mpv`, `iperf3`
- Crea el virtualenv Python en `/opt/adhoc-node/venv`
- Descarga/genera 25 canciones en `/opt/adhoc-node/music`
- Registra el servicio systemd `adhoc-node.service`
- Configura firewalld (puertos 8080/tcp, 5004/udp, 5005/udp)

> El script auto-detecta la interfaz WiFi. Si falla: `sudo ADHOC_IFACE=wlan0 bash scripts/install-fedora.sh`

---

## 3. Verificar que la interfaz WiFi soporta IBSS

```bash
iw list | grep -A 10 "Supported interface modes"
```

Debe aparecer `IBSS` en la lista. Si no aparece, el chipset no soporta ad-hoc y hay que usar otro adaptador.

---

## 4. ON — Activar la red AD-HOC

```bash
sudo bash scripts/adhoc-on.sh
```

Qué hace:
1. Guarda la conexión WiFi actual para poder restaurarla después
2. Libera la interfaz de NetworkManager **solo en RAM** (sin tocar archivos permanentes)
3. Escanea durante 4 segundos redes con SSID `ADHOC-STREAM`
4. Si encuentra una red → se une a la de mejor señal
5. Si no encuentra ninguna → crea una nueva y se convierte en posible Master
6. Asigna IP fija `192.168.99.X` derivada del `machine-id` del nodo (único por máquina)

Al terminar imprime:
```
[ON] === AD-HOC ACTIVO ===
     Interfaz : wlan0
     SSID     : ADHOC-STREAM
     IP local : 192.168.99.42
     Cell ID  : 02:xx:xx:xx:xx:xx
```

> **Mientras la red AD-HOC está activa, el internet normal no funciona.** Esto es esperado.

---

## 5. OFF — Restaurar internet normal

```bash
sudo bash scripts/adhoc-off.sh
```

Qué hace:
1. Sale de la red IBSS
2. Resetea la interfaz a modo managed
3. Devuelve el control a NetworkManager
4. Elimina `/etc/NetworkManager/conf.d/99-adhoc-unmanaged.conf` si existe (limpia instalaciones anteriores)
5. Reinicia NetworkManager
6. Reconecta a la red WiFi que había antes

> Si tu internet está caído por haber corrido scripts viejos, ejecuta esto primero.

---

## 6. Verificar el estado de la red AD-HOC

```bash
# Ver si estás en modo IBSS
iw dev wlan0 info

# Ver nodos vecinos que detecta la interfaz
iw dev wlan0 station dump

# Ver IPs en la red
ip addr show wlan0

# Ping a otro nodo (reemplaza .X con su IP)
ping 192.168.99.X
```

---

## 7. Arrancar el daemon del nodo

Una vez que la red AD-HOC está activa (paso 4):

```bash
# Iniciar el daemon
sudo systemctl start adhoc-node.service

# Ver logs en tiempo real
sudo journalctl -u adhoc-node.service -f

# Dashboard web (desde cualquier nodo en la misma red)
# Abrir en navegador: http://192.168.99.X:8080
```

El daemon hace automáticamente:
- Configura la red (llama a `network-setup.sh`)
- Decide si este nodo es Master (más recursos → CPU, RAM)
- Si es Master: selecciona canción aleatoria y hace streaming por multicast UDP `239.255.42.42:5004`
- Si es cliente: recibe el stream y lo reproduce con `mpv`

---

## 8. Indicadores del dashboard (http://IP:8080)

| Indicador | Descripción |
|---|---|
| Tasa de transmisión | Kbps actuales del stream |
| Nodos activos | Lista de IPs visibles en la red |
| Señal por nodo | dBm de cada vecino (`iw station dump`) |
| Modulación | Modo de transmisión WiFi actual |
| Canciones locales | Las 25 canciones de este nodo |
| Canción en streaming | La que transmite/reproduce ahora |

---

## 9. Forzar una canción específica (desde el Master)

```bash
# Reemplaza IP con la del nodo Master y NOMBRE con el archivo
curl -X POST http://192.168.99.X:8080/api/play \
     -H "Content-Type: application/json" \
     -d '{"song": "song_03.mp3"}'
```

---

## 10. Múltiples redes independientes (nodos fuera de rango)

Cuando un nodo pierde señal de la red principal:
1. `network-setup.sh` no encuentra ninguna red al escanear
2. Crea automáticamente una nueva celda IBSS con BSSID aleatorio
3. Se convierte en Master de esa subred
4. Los nodos cercanos a él se unen a su red

No requiere intervención manual.

---

## Resumen de comandos

```bash
# Instalar (una vez, con internet)
sudo bash scripts/install-fedora.sh

# Encender AD-HOC
sudo bash scripts/adhoc-on.sh

# Apagar AD-HOC y restaurar internet
sudo bash scripts/adhoc-off.sh

# Arrancar/detener daemon
sudo systemctl start adhoc-node.service
sudo systemctl stop adhoc-node.service

# Logs
sudo journalctl -u adhoc-node.service -f
```

---

## Solución de problemas

**No detecta interfaz WiFi automáticamente**
```bash
ls /sys/class/net/*/wireless -d   # ver interfaces disponibles
sudo ADHOC_IFACE=wlan0 bash scripts/adhoc-on.sh
```

**Error: `IBSS` no aparece en `iw list`**
El adaptador no soporta modo ad-hoc. Usar un adaptador USB WiFi compatible (chipsets Atheros AR9271, Ralink RT5372, Realtek RTL8188).

**Internet no vuelve después de adhoc-off**
```bash
nmcli device status               # ver estado de la interfaz
nmcli device wifi connect "NOMBRE_RED" password "CONTRASEÑA"
```

**`iw dev wlan0 set type ibss` falla con "Device or resource busy"**
NetworkManager todavía controla la interfaz:
```bash
nmcli device set wlan0 managed no
nmcli device disconnect wlan0
```

**El nodo no ve a otros nodos**
- Verificar que todos usan el mismo SSID (`ADHOC-STREAM`) y frecuencia (`2412 MHz = canal 1`)
- Verificar con `iw dev wlan0 station dump` — si está vacío, no hay vecinos en rango
- Probar cambiar canal: `sudo ADHOC_FREQ=2437 bash scripts/adhoc-on.sh` (canal 6)
