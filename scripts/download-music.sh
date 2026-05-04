#!/usr/bin/env bash
set -euo pipefail

# download-music.sh — Descarga 25 canciones de la playlist de YouTube.
# Fuente: Playlist Reggaeton No Copyright
#   https://youtube.com/playlist?list=PLDzVDC0HAjdwbi550vHEVEBhoMzKHFByN
# Uso educativo — Proyecto escolar AD-HOC Streaming Node.

MUSIC_DIR="${1:-/opt/adhoc-node/music}"
YTDLP_PLAYLIST="${YTDLP_PLAYLIST:-https://youtube.com/playlist?list=PLDzVDC0HAjdwbi550vHEVEBhoMzKHFByN}"
mkdir -p "$MUSIC_DIR"

echo "[MUSIC] Limpiando canciones existentes..."
find "$MUSIC_DIR" -maxdepth 1 \( -name "*.mp3" -o -name "*.ogg" -o -name "*.m4a" \) -delete

if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "[MUSIC][ERROR] yt-dlp no está instalado. Instálalo con: sudo dnf install yt-dlp"
    exit 1
fi

echo "[MUSIC] Descargando 25 canciones de: $YTDLP_PLAYLIST"
(
    cd "$MUSIC_DIR"
    yt-dlp \
        --playlist-random \
        --max-downloads 25 \
        -x --audio-format mp3 --audio-quality 192K \
        -o "song_%(autonumber)02d.%(ext)s" \
        "$YTDLP_PLAYLIST"
)

total=$(find "$MUSIC_DIR" -maxdepth 1 \( -name "*.mp3" -o -name "*.ogg" -o -name "*.m4a" \) | wc -l)
echo "[MUSIC] Total canciones descargadas: $total"

if [ "$total" -eq 0 ]; then
    echo "[MUSIC][ERROR] No se descargó ninguna canción. Verifica la conexión y que yt-dlp esté actualizado (sudo yt-dlp -U)."
    exit 1
fi
