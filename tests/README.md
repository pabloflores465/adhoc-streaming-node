# tests/

Pruebas del sistema AD-HOC.

## Contenido

- `test_network.py` — Prueba heartbeats UDP, descubrimiento de peers, detección de conflictos IP y song_request broadcast.
- `test_streamer.py` — Prueba inicio/parada de ffmpeg con archivo dummy local y desde URL HTTP.
- `test_api.py` — Prueba endpoints Flask: status, dashboard, force-song, force-master, servicio de música y path traversal.

## Ejecutar

```bash
cd src
python3 -m pytest ../tests/ -v
```

O individualmente:

```bash
cd tests
python3 test_network.py
python3 test_streamer.py
python3 test_api.py
```

## Requisitos para tests

- `ffmpeg` instalado (para generar audio dummy).
- Puerto UDP libre (usa 59999/54321 en localhost).
