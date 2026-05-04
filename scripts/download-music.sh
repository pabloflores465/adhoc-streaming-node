#!/usr/bin/env bash
set -euo pipefail

# download-music.sh — Descarga/genera 25 canciones <= 90s para el nodo.
# Prioridad: yt-dlp (playlist CC) > wget URLs locales > generar con ffmpeg.
#
# Fuente principal de música (No Copyright / libre de derechos):
#   Canal: https://youtu.be/xuBbiiwO9Ow
#   Playlist completa: establece YTDLP_PLAYLIST al URL de la playlist del canal.
#   Uso educativo — Proyecto escolar AD-HOC Streaming Node.

MUSIC_DIR="${1:-/opt/adhoc-node/music}"
MAX_DURATION=90
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL_FILE="${REPO_ROOT}/config/music-urls.txt"
mkdir -p "$MUSIC_DIR"

echo "[MUSIC] Objetivo: 25 canciones en $MUSIC_DIR (max ${MAX_DURATION}s)"

# Limpiar archivos inválidos (duración 0 o corruptos) antes de contar
if command -v ffprobe >/dev/null 2>&1; then
    echo "[MUSIC] Verificando archivos existentes..."
    for f in "$MUSIC_DIR"/*.mp3 "$MUSIC_DIR"/*.ogg "$MUSIC_DIR"/*.m4a; do
        [ -f "$f" ] || continue
        dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null || echo "0")
        # remove if duration is 0, empty, or less than 5 seconds
        if awk "BEGIN{exit !($dur+0 < 5)}"; then
            echo "[MUSIC] Eliminando archivo inválido/dummy: $(basename "$f")"
            rm -f "$f"
        fi
    done
fi

# --- Método 1: yt-dlp desde playlist/canal de YouTube (No Copyright) ---
# Ref: https://youtu.be/xuBbiiwO9Ow — sustituye con la URL de la playlist completa
# para obtener más variedad. yt-dlp selecciona 25 canciones en orden aleatorio.
YTDLP_PLAYLIST="${YTDLP_PLAYLIST:-https://youtu.be/xuBbiiwO9Ow}"
if command -v yt-dlp >/dev/null 2>&1; then
    echo "[MUSIC] Usando yt-dlp: $YTDLP_PLAYLIST"
    (
        cd "$MUSIC_DIR"
        yt-dlp \
            --yes-playlist \
            --playlist-random \
            -x --audio-format mp3 --audio-quality 192K \
            --match-filter "duration <= 300" \
            --max-downloads 25 \
            -o "song_%(autonumber)02d.%(ext)s" \
            "$YTDLP_PLAYLIST" 2>/dev/null || true
    )
fi

# --- Método 2: wget/curl desde URLs locales ---
if [ -f "$URL_FILE" ]; then
    count=$(find "$MUSIC_DIR" -maxdepth 1 \( -name "*.mp3" -o -name "*.ogg" -o -name "*.m4a" \) | wc -l)
    while IFS= read -r url && [ "$count" -lt 25 ]; do
        [ -z "$url" ] && continue
        [[ "$url" =~ ^# ]] && continue
        idx=$((count + 1))
        out="$MUSIC_DIR/song_$(printf '%02d' $idx)"
        echo "[MUSIC] Descargando $url ..."
        if wget -q -O "${out}.tmp" "$url" 2>/dev/null || curl -sL -o "${out}.tmp" "$url" 2>/dev/null; then
            if ffmpeg -y -i "${out}.tmp" -t "$MAX_DURATION" -c:a libmp3lame -b:a 192k "${out}.mp3" 2>/dev/null; then
                count=$((count + 1))
            fi
            rm -f "${out}.tmp"
        fi
    done < "$URL_FILE"
fi

# --- Método 3: Generar con ffmpeg (fallback garantizado) ---
existing=$(find "$MUSIC_DIR" -maxdepth 1 \( -name "*.mp3" -o -name "*.ogg" -o -name "*.m4a" \) | wc -l)
needed=$((25 - existing))

if [ "$needed" -gt 0 ]; then
    echo "[MUSIC] Generando $needed pistas de prueba con ffmpeg..."
    for i in $(seq 1 $needed); do
        idx=$((existing + i))
        out="$MUSIC_DIR/song_$(printf '%02d' $idx).mp3"
        # Frecuencia base cambiante + armónicos para que suenen distintas
        base=$((200 + (i * 47) % 600))
        harm2=$((base * 2))
        harm3=$((base * 3))
        # Patrón rítmico simple: beep cada 0.5s
        ffmpeg -y -f lavfi -i "
            aevalsrc=
            sin(2*PI*$base*t)*sin(2*PI*2*t)
            + 0.3*sin(2*PI*$harm2*t)*sin(2*PI*2*t + PI/4)
            + 0.15*sin(2*PI*$harm3*t)*sin(2*PI*2*t + PI/2)
            :s=44100:d=$MAX_DURATION
        " -c:a libmp3lame -b:a 192k "$out" 2>/dev/null
    done
fi

echo "[MUSIC] Total canciones: $(find "$MUSIC_DIR" -maxdepth 1 \( -name '*.mp3' -o -name '*.ogg' -o -name '*.m4a' \) | wc -l)"
