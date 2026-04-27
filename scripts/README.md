# scripts/

Scripts de inicialización y administración del nodo.

## Archivos

- `install.sh` — Instala dependencias en **Ubuntu/Debian** (apt-get).
- `install-fedora.sh` — Instala dependencias en **Fedora 43+** (dnf5 + rpmfusion-free). Incluye configuración de NetworkManager unmanaged, SELinux y firewalld.
- `init-node.sh` — Entrypoint principal ejecutado por systemd.
- `network-setup.sh` — Configura interfaz Wi-Fi en modo IBSS con cell ID dinámico al boot.
- `network-rejoin.sh` — Reescanea IBSS y migra a celda mejor si la actual es débil.
- `master-election.sh` — Algoritmo de elección de Master por recursos.
- `streaming-server.sh` — Inicia ffmpeg como servidor de streaming UDP.
- `streaming-client.sh` — Inicia receptor de streaming.
- `download-music.sh` — Descarga/genera 25 canciones CC de ≤90s para el nodo.

## Uso

Todos los scripts requieren privilegios de root para manipular interfaces de red.
