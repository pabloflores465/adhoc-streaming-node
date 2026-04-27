# AD-HOC Streaming Node

Red AD-HOC inalámbrica para transmisión de streaming en tiempo real con GNU/Linux.

## Estructura

| Directorio | Propósito |
|------------|-----------|
| `docs/` | Reporte gráfico en LaTeX |
| `scripts/` | Scripts de inicialización y setup de red |
| `systemd/` | Unidades de servicio para autoarranque |
| `src/` | Código fuente del daemon principal |
| `config/` | Configuraciones de red y parámetros |
| `ansible/` | Playbooks para despliegue masivo |
| `music/` | 25 canciones locales por nodo |
| `tests/` | Pruebas unitarias y de integración |

## Visión Holística

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NODO AD-HOC STREAMING                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  systemd     │→ │ init-node.sh │→ │ network-     │→ │ node-daemon  │    │
│  │  (boot)      │  │              │  │ setup.sh     │  │ .py (Python) │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────┬───────┘    │
│                                                               │             │
│     ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────┴────────┐   │
│     │ Heartbeat  │  │  Streamer  │  │  Flask     │  │  State Persist  │   │
│     │  UDP       │  │  ffmpeg    │  │  :8080     │  │  JSON           │   │
│     └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────────────────┘   │
│           │               │               │                                 │
│     IBSS Cell A     multicast      Dashboard web                           │
│     (cell_id:xx)   239.255.42      /music/ /api/                          │
│           │               │               │                                 │
│     ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐                        │
│     │  Master A │   │  Cliente 1│   │  Cliente 2│                        │
│     │  (ffmpeg) │   │  (mpv)    │   │  (mpv)    │                        │
│     └───────────┘   └───────────┘   └───────────┘                        │
│                                                                             │
│     IBSS Cell B ←────── re-fusión por proximidad ──────→ IBSS Cell A      │
│     (cuando se acercan físicamente)                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Flujo de Arranque

1. Boot desde USB con Ubuntu Server instalado.
2. systemd lanza `adhoc-node.service`.
3. `init-node.sh` lee estado previo (`state.json`) y reintenta celda conocida.
4. El script de red escanea IBSS con SSID `ADHOC-STREAM`.
5. Si encuentra una o más → se une a la de **mejor señal**.
6. Si no hay ninguna → genera cell ID aleatorio y crea red propia, declarándose Master.
7. El nodo publica su lista de canciones locales vía UDP multicast.
8. El Master elige canción de TODA la red (locales + peers vía HTTP) e inicia streaming.
9. **Cualquier nodo puede solicitar canción:** desde su dashboard, clickea el nombre de cualquier canción de la red (local o remota).
10. El nodo emite `song_request` por UDP broadcast.
11. El Master recibe la solicitud, resuelve si es local o remota (HTTP), y la reproduce.
12. Si la canción ya está sonando, el Master ignora la solicitud (evita reinicio).
13. Si un cliente pierde Master y llega uno nuevo con canción diferente → **PAUSA automática**.
14. Usuario presiona **Play** para reanudar.
15. Cada 60s el daemon reescanea IBSS y migra a celda mejor si es necesario.
16. Panel web en `:8080` muestra indicadores en tiempo real.

## Instalación Rápida

```bash
sudo ./scripts/install.sh
sudo systemctl enable --now adhoc-node.service
```

## Logs

Todos los componentes escriben a `/opt/adhoc-node/logs/`:

| Archivo | Origen |
|---------|--------|
| `daemon.log` | Python daemon (rotativo, 10MB) |
| `network.log` | Scripts bash de red y rejoin |
| `journal` | `journalctl -u adhoc-node.service` |

```bash
sudo tail -f /opt/adhoc-node/logs/daemon.log
sudo tail -f /opt/adhoc-node/logs/network.log
sudo journalctl -u adhoc-node.service -f
```

## Requisitos

- Ubuntu 22.04/24.04 LTS en USB bootable
- Tarjeta Wi-Fi con modo IBSS/ad-hoc soportado
- Python 3.10+
- `iw`, `wpasupplicant`, `ffmpeg`, `vlc` o `mpv`

## Licencia

Proyecto académico - Evaluación final.
