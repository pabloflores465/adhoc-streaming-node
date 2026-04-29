# Documentación Técnica — Red AD-HOC de Streaming en Tiempo Real

## Índice
1. [Visión general](#1-visión-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Capa de red — IBSS](#3-capa-de-red--ibss)
4. [Descubrimiento de nodos y elección de Master](#4-descubrimiento-de-nodos-y-elección-de-master)
5. [Pipeline de streaming](#5-pipeline-de-streaming)
6. [Dashboard web y API REST](#6-dashboard-web-y-api-rest)
7. [Persistencia y recuperación de estado](#7-persistencia-y-recuperación-de-estado)
8. [Separación de redes y re-unión](#8-separación-de-redes-y-re-unión)
9. [Scripts de operación](#9-scripts-de-operación)
10. [Variables de entorno](#10-variables-de-entorno)
11. [Referencia de puertos y direcciones](#11-referencia-de-puertos-y-direcciones)

---

## 1. Visión general

El sistema implementa una red inalámbrica descentralizada (IBSS/802.11 ad-hoc) donde cada nodo:

- Arranca desde USB con Fedora 43
- Se une automáticamente a la red activa de mayor señal, o crea una nueva si no encuentra ninguna
- Tiene un catálogo local de 25 canciones propias
- Compite por ser Master según sus recursos de hardware
- El Master transmite audio por multicast UDP en tiempo real a todos los nodos
- Cada nodo muestra un dashboard web con métricas en vivo

---

## 2. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────┐
│  systemd: adhoc-node.service                                │
│  └─ init-node.sh                                            │
│      ├─ network-setup.sh     ← configura IBSS               │
│      ├─ master-election.sh   ← calcula score local          │
│      └─ node-daemon.py       ← orquestador principal        │
│          ├─ AdhocManager     ← heartbeats UDP + peers       │
│          ├─ Streamer         ← ffmpeg server / mpv client   │
│          ├─ monitor.py       ← métricas iw / psutil         │
│          └─ app.py (Flask)   ← dashboard + API REST         │
└─────────────────────────────────────────────────────────────┘
```

### Componentes Python

| Módulo | Archivo | Responsabilidad |
|---|---|---|
| `AdhocManager` | `src/network/adhoc_manager.py` | Heartbeats, descubrimiento de peers, DHCP ligero, resolución de conflictos IP |
| `Streamer` | `src/streaming/streamer.py` | Control de ffmpeg (servidor) y mpv (cliente), detección de EOF |
| `monitor` | `src/monitoring/monitor.py` | Parseo de `iw station dump`, métricas de CPU/RAM, lista de canciones |
| `app` | `src/web/app.py` | Flask: dashboard HTML, API REST, servidor de archivos de música |
| `state` | `src/node/state.py` | Persistencia JSON de cell_id, rol y canción actual |
| `NodeDaemon` | `src/node/node-daemon.py` | Orquestador: hilos de heartbeat, cleanup, IP conflicts, rejoin, master logic |

---

## 3. Capa de red — IBSS

### Modo IBSS (Independent Basic Service Set)

A diferencia de WiFi normal (infraestructura con AP), IBSS permite comunicación directa entre dispositivos sin punto de acceso. Cada "celda" IBSS se identifica por un BSSID (MAC de 6 bytes).

### Configuración al arrancar (`network-setup.sh`)

```
1. nmcli device set <IFACE> managed no   ← libera de NetworkManager (solo RAM)
2. ip link set <IFACE> down
3. ip addr flush dev <IFACE>
4. iw dev <IFACE> ibss leave             ← limpia estado IBSS anterior
5. iw dev <IFACE> set type managed       ← modo managed para poder escanear
6. ip link set <IFACE> up
7. iw dev <IFACE> scan ap-force          ← dispara escaneo activo
8. sleep 4                               ← espera que el hardware complete
9. iw dev <IFACE> scan dump              ← lee resultados
   └─ awk filtra SSID == "ADHOC-STREAM"
10. Elegir BSSID de mayor señal (dBm)
    ├─ Si existe: iw ibss join <SSID> <FREQ> fixed-freq <BSSID>
    └─ Si no:     iw ibss join <SSID> <FREQ> fixed-freq <MAC-aleatoria>
11. ip addr add 192.168.99.<X>/24        ← X derivado de machine-id
```

**Idempotencia:** Si la interfaz ya está en IBSS con la IP correcta, el script termina inmediatamente sin reconfigurar (evita doble escaneo cuando el servicio arranca después de `adhoc-on.sh`).

### Asignación de IP determinista

```bash
HEX_BYTE = primeros 2 caracteres de /etc/machine-id
OCTET    = (hex2dec(HEX_BYTE) % 240) + 10   # rango: 10–249
IP       = 192.168.99.<OCTET>
```

Esto garantiza que cada máquina siempre tenga la misma IP sin necesidad de DHCP.

### Estado NO-CARRIER en IBSS

Con un solo nodo en la red, la interfaz muestra `NO-CARRIER`. Esto es normal en IBSS — el "carrier" solo se establece cuando hay al menos otro nodo. No afecta el funcionamiento del daemon.

---

## 4. Descubrimiento de nodos y elección de Master

### Heartbeats UDP (`AdhocManager`)

Cada nodo emite un heartbeat JSON cada 3 segundos simultáneamente a:
- Broadcast: `255.255.255.255:5005`
- Multicast: `239.255.42.42:5005`

```json
{
  "type": "heartbeat",
  "node_id": "14139bb8",
  "timestamp": 1745956889.0,
  "score": 5842,
  "ip": "192.168.99.30",
  "is_master": true,
  "songs": ["song_01.mp3", "song_02.mp3", "..."]
}
```

Un peer se considera muerto si no se recibe heartbeat en 15 segundos.

### Elección de Master (`master-election.sh`)

```
SCORE = RAM_libre_MB + (CPU_cores × 1000) - (load_avg × 500)
```

El nodo con mayor score es Master. En caso de empate, gana el que tiene `is_master=true` en sus heartbeats previos (estabilidad).

**Anti-split-brain:** Antes de tomar control como Master, el nodo hace *sniffing* del puerto multicast durante 2 segundos. Si detecta paquetes, verifica si hay otro Master con mejor score antes de tomar el control.

### Creador de red vs. Master

- El creador de la celda IBSS (primer nodo) recibe `is_master=1` inicial por heurística (flag `/tmp/adhoc-master.flag`)
- Pero puede ceder el liderazgo si llega un nodo con mayor score
- El rol se reevalúa continuamente en `_master_logic()` cada 2 segundos

---

## 5. Pipeline de streaming

### Master → transmisión multicast

```
Archivo MP3 local  ─┐
URL HTTP de peer  ──┤─► ffmpeg ─► UDP multicast 239.255.42.42:5004 (MPEG-TS)
                    └   (-re -c:a libmp3lame 192k -f mpegts)
```

- `-re`: reproduce a velocidad real (1x), no en ráfaga
- `ttl=1`: el multicast no sale de la red local
- `pkt_size=1316`: tamaño óptimo para MPEG-TS sobre UDP

### Cliente → recepción y reproducción

```
UDP multicast 239.255.42.42:5004 ─► mpv --no-cache --no-video
                                         (o ffplay como fallback)
```

### Selección de canción (Master)

1. Recopila canciones locales + canciones de todos los peers (vía heartbeats)
2. Elige aleatoriamente de la lista completa
3. Si la canción es remota: la descarga por HTTP desde `http://<peer-ip>:8080/music/<nombre>`
4. Si hay `forced_song` pendiente (vía API): la prioriza

### Watchdog de EOF

Un hilo `_watchdog` espera `proc.wait()` sobre el proceso ffmpeg/mpv. Al terminar notifica al daemon para iniciar la siguiente canción (Master) o reiniciar la recepción (cliente).

---

## 6. Dashboard web y API REST

URL: `http://192.168.99.<X>:8080`

### Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Dashboard HTML (auto-refresh 3s) |
| `GET` | `/api/status` | Estado completo en JSON |
| `POST` | `/api/force-song` | Forzar canción específica (form: `song=nombre.mp3`) |
| `POST` | `/api/force-master` | Forzar este nodo como Master |
| `POST` | `/api/toggle-pause` | Pausar/reanudar reproducción en cliente |
| `GET` | `/music/<archivo>` | Servir archivo de música para peers |

### Indicadores en el dashboard

| Indicador | Fuente |
|---|---|
| Tasa de transmisión activa | `iw dev <iface> station dump` → campo `tx_bitrate`/`rx_bitrate` |
| Nodos activos | Peers vivos en `AdhocManager.peers` |
| Nivel de señal por nodo | `iw station dump` → campo `signal` (dBm) |
| Modulación | Inferida de `rx_bitrate` + MCS index (`iw station dump`) |
| Canciones locales | `ls /opt/adhoc-node/music/*.mp3` |
| Canción en streaming | Estado interno de `Streamer.current_song` |

---

## 7. Persistencia y recuperación de estado

Archivo: `/opt/adhoc-node/state/node-state.json`

```json
{
  "cell_id": "02:a3:f1:7c:2d:88",
  "is_master": true,
  "current_song": "song_12.mp3",
  "node_id": "14139bb8",
  "timestamp": 1745956900.0
}
```

Al arrancar, `init-node.sh` lee este archivo. Si tiene menos de 5 minutos de antigüedad, pasa `PREFERRED_CELL` a `network-setup.sh`, que intenta re-unirse a la misma celda antes de hacer escaneo general. Esto acelera la reconexión tras un reinicio.

---

## 8. Separación de redes y re-unión

### Separación automática

Si un nodo pierde señal de la red principal, en el siguiente ciclo de `network-setup.sh` (invocado por `network-rejoin.sh` cada 60 segundos):

1. Escanea y no encuentra ninguna red `ADHOC-STREAM`
2. Genera un BSSID aleatorio nuevo
3. Crea su propia celda IBSS
4. Toma el rol de Master de esa subred
5. Acepta a los nodos que tenga en rango

### Re-unión automática (`network-rejoin.sh`)

El daemon llama a `network-rejoin.sh` cada 60 segundos. Si detecta que hay una celda de mayor señal que la actual, migra a ella. Esto implementa el requisito de "unirse a una red activa si está en cobertura".

---

## 9. Scripts de operación

| Script | Uso | Descripción |
|---|---|---|
| `adhoc-on.sh` | `sudo bash scripts/adhoc-on.sh` | Configura IBSS + arranca daemon |
| `adhoc-off.sh` | `sudo bash scripts/adhoc-off.sh` | Para daemon + restaura internet |
| `install-fedora.sh` | `sudo bash scripts/install-fedora.sh` | Instala dependencias, venv, música, systemd (una sola vez) |
| `reset-node.sh` | `sudo bash scripts/reset-node.sh` | Limpieza total, deja el sistema como nuevo |
| `network-setup.sh` | Llamado por systemd | Configura la interfaz IBSS |
| `master-election.sh` | Llamado por init-node.sh | Calcula score y decide rol inicial |
| `download-music.sh` | Llamado por install-fedora.sh | Descarga/genera 25 canciones |

---

## 10. Variables de entorno

Definidas en `config/adhoc.conf` y en `systemd/adhoc-node.service`:

| Variable | Default | Descripción |
|---|---|---|
| `ADHOC_IFACE` | `wlan0` | Interfaz inalámbrica |
| `ADHOC_SSID` | `ADHOC-STREAM` | SSID de la red ad-hoc |
| `ADHOC_FREQ` | `2412` | Frecuencia en MHz (canal 1) |
| `ADHOC_NET` | `192.168.99` | Prefijo de red /24 |
| `ADHOC_MULTI` | `239.255.42.42` | Dirección multicast del stream |
| `ADHOC_PORT` | `5004` | Puerto UDP del stream |
| `ADHOC_PLAYER` | `mpv` | Reproductor de audio en clientes |
| `ADHOC_MUSIC` | `/opt/adhoc-node/music` | Directorio de música local |

Cambiar la interfaz: `sudo ADHOC_IFACE=wlp3s0 bash scripts/adhoc-on.sh`

---

## 11. Referencia de puertos y direcciones

| Puerto/Dirección | Protocolo | Uso |
|---|---|---|
| `239.255.42.42:5004` | UDP multicast | Stream de audio MPEG-TS |
| `255.255.255.255:5005` | UDP broadcast | Heartbeats entre nodos |
| `239.255.42.42:5005` | UDP multicast | Heartbeats entre nodos |
| `0.0.0.0:8080` | TCP (HTTP) | Dashboard web + API REST + servidor de música |
| `192.168.99.0/24` | — | Subred de la celda AD-HOC |
