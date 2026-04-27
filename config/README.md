# config/

Configuraciones de red y parámetros del nodo.

## Archivos

- `adhoc.conf` — Variables de entorno por defecto (SSID, frecuencia, rango IP, etc.).
- `music-urls.txt` — URLs de archivos MP3/OGG Creative Commons para descarga automática.
  Puedes definir `YTDLP_PLAYLIST` para usar yt-dlp en vez de URLs directas.

## Uso

El servicio systemd puede cargar estas variables vía `EnvironmentFile=-/opt/adhoc-node/repo/config/adhoc.conf`.
