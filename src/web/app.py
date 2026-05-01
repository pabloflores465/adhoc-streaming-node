#!/usr/bin/env python3
"""
app.py — Panel web y API REST para indicadores y control externo.
"""

import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, request, render_template_string, send_from_directory, abort

app = Flask(__name__)

# Referencias inyectadas por node-daemon
_daemon_state = {
    "master": False,
    "current_song": "Ninguna",
    "peers": {},
    "status_fn": None,
    "force_song_fn": None,
    "force_master_fn": None,
    "toggle_pause_fn": None,
}

DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>AD-HOC Node {{ node_id }}</title>
  <style>
    body { font-family: sans-serif; background:#111; color:#0f0; padding:2rem; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap:1rem; }
    .card { background:#1a1a1a; border:1px solid #333; padding:1rem; border-radius:8px; }
    h1 { color:#0ff; }
    .role-banner { padding:.6rem 1.2rem; border-radius:6px; display:inline-block; margin-bottom:1rem; font-size:1.1rem; font-weight:bold; }
    .role-master { background:#3a2e00; color:gold; border:1px solid gold; }
    .role-client { background:#1a1a2e; color:#8888ff; border:1px solid #444; }
    .paused-badge { background:#500; color:red; border:1px solid red; padding:.3rem .8rem; border-radius:4px; margin-left:.8rem; }
    .empty-hint { color:#555; font-style:italic; font-size:.9rem; }
    table { width:100%; border-collapse:collapse; margin-top:.5rem; }
    th,td { text-align:left; padding:.3rem .5rem; border-bottom:1px solid #333; }
    th { color:#0ff; }
    button { background:#0f0; color:#000; border:none; padding:.5rem 1rem; cursor:pointer; border-radius:4px; }
    button:hover { background:#0c0; }
    button.btn-master { background:#c90; color:#000; }
    button.btn-master:hover { background:#fa0; }
    button.btn-pause { background:#444; color:#fff; }
    button.btn-pause:hover { background:#666; }
    input[type=text] { padding:.4rem; width:60%; background:#222; color:#0f0; border:1px solid #444; border-radius:4px; }
    .self-node { color:#0f0; }
    .peer-node { color:#0af; }
  </style>
</head>
<body>
  <h1>AD-HOC Streaming Node — {{ node_id }}</h1>

  <div>
    <span class="role-banner {{ 'role-master' if is_master else 'role-client' }}">
      {% if is_master %}★ MASTER — este nodo elige y transmite las canciones{% else %}◎ Cliente — recibiendo stream del Master{% endif %}
    </span>
    {% if paused %}<span class="paused-badge">⏸ PAUSADO</span>{% endif %}
    <span style="color:#555; margin-left:1rem; font-size:.9rem">Celda: <code>{{ cell_id }}</code></span>
  </div>

  <div class="grid" style="margin-top:1rem">
    <div class="card">
      <h3>{% if is_master %}Control de transmisión{% else %}Solicitar canción{% endif %}</h3>
      <p><strong>Tasa TX:</strong> {{ tx_rate }}</p>
      <p><strong>Canción en streaming:</strong> {{ current_song }}</p>

      {% if not is_master %}
      <p class="empty-hint" style="margin-bottom:.5rem">Como cliente, puedes solicitar una canción — el Master la recibirá y la pondrá.</p>
      {% endif %}

      <form action="/api/force-song" method="post" style="margin-top:.5rem">
        <input type="text" name="song" placeholder="nombre_cancion.mp3">
        <button type="submit">{% if is_master %}Forzar canción{% else %}Solicitar canción{% endif %}</button>
      </form>

      {% if not is_master %}
      <form action="/api/force-master" method="post" style="margin-top:.5rem">
        <button type="submit" class="btn-master">Tomar control (ser Master)</button>
      </form>
      {% endif %}

      <form action="/api/toggle-pause" method="post" style="margin-top:.5rem">
        <button type="submit" class="btn-pause">{% if paused %}▶ Reanudar{% else %}⏸ Pausar reproducción{% endif %}</button>
      </form>

      <p style="margin-top:1rem"><strong>Canciones disponibles en la red:</strong></p>
      <div style="display:flex;flex-wrap:wrap;gap:0.3rem;">
        {% for song_name, source, is_local in all_network_songs %}
        <form action="/api/force-song" method="post" style="display:inline">
          <input type="hidden" name="song" value="{{ song_name }}">
          <button type="submit" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:{% if is_local %}#0f0{% else %}#0af{% endif %};color:{% if is_local %}#000{% else %}#fff{% endif %}">
            {{ song_name }} {% if is_local %}(local){% else %}[{{ source }}]{% endif %}
          </button>
        </form>
        {% endfor %}
        {% if not all_network_songs %}
        <span class="empty-hint">Sin canciones en la red aún.</span>
        {% endif %}
      </div>
    </div>

    <div class="card">
      <h3>Peers activos ({{ peer_count }})</h3>
      {% if peers %}
      <table>
        <tr><th>Node ID</th><th>IP</th><th>Score</th><th>Rol</th><th>Canciones</th></tr>
        {% for nid, info in peers.items() %}
        <tr>
          <td>{{ nid }}</td>
          <td>{{ info.ip }}</td>
          <td>{{ info.score }}</td>
          <td>{% if info.is_master %}<span style="color:gold">Master</span>{% else %}Cliente{% endif %}</td>
          <td>{{ info.songs|length if info.songs else 0 }}</td>
        </tr>
        {% endfor %}
      </table>
      {% else %}
      <p class="empty-hint">Sin peers detectados. Los nodos aparecen cuando envían heartbeats (cada 3s).</p>
      {% endif %}
    </div>

    <div class="card">
      <h3>Inventario de canciones por nodo</h3>
      <p><strong class="self-node">{{ node_id }}</strong> <span style="color:#555">(este nodo)</span>:</p>
      <ul>
        {% for s in local_songs %}
        <li>{{ s }}</li>
        {% else %}
        <li class="empty-hint">Sin canciones locales</li>
        {% endfor %}
      </ul>
      {% for nid, info in peers.items() %}
      <p style="margin-top:.5rem"><strong class="peer-node">{{ nid }}</strong> <span style="color:#555">({{ info.ip }})</span>:</p>
      <ul>
        {% for s in info.songs %}
        <li>{{ s }}</li>
        {% else %}
        <li class="empty-hint">Sin canciones reportadas aún</li>
        {% endfor %}
      </ul>
      {% else %}
      {% if not local_songs %}
      <p class="empty-hint">Sin peers conectados todavía.</p>
      {% endif %}
      {% endfor %}
    </div>

    <div class="card">
      <h3>Señal y Modulación</h3>
      <p><strong>Modulación:</strong> {{ modulation }}</p>
      {% if signal_levels %}
      <table>
        <tr><th>MAC</th><th>Señal</th></tr>
        {% for mac, sig in signal_levels.items() %}
        <tr><td>{{ mac }}</td><td>{{ sig }}</td></tr>
        {% endfor %}
      </table>
      {% else %}
      <p class="empty-hint">Sin estaciones detectadas aún. Los datos de señal aparecen cuando hay al menos un peer asociado en la red IBSS.</p>
      {% endif %}
    </div>

    <div class="card">
      <h3>Canciones locales ({{ local_songs|length }})</h3>
      <ul>
        {% for s in local_songs %}
        <li>{{ s }}</li>
        {% else %}
        <li class="empty-hint">Sin canciones en el directorio local.</li>
        {% endfor %}
      </ul>
    </div>

    <div class="card">
      <h3>Sistema</h3>
      <p>CPU: {{ system.cpu_percent }}%</p>
      <p>RAM libre: {{ system.ram_available_mb }} MB</p>
      <p>Load avg: {{ system.load_avg }}</p>
    </div>
  </div>

  <script>
    setTimeout(() => location.reload(), 3000);
  </script>
</body>
</html>
"""


@app.route("/")
def dashboard():
    if _daemon_state["status_fn"]:
        data = _daemon_state["status_fn"]()
    else:
        data = {}
    return render_template_string(DASHBOARD_HTML, **data)


@app.route("/api/status")
def api_status():
    if _daemon_state["status_fn"]:
        return jsonify(_daemon_state["status_fn"]())
    return jsonify({"error": "daemon no listo"}), 503


@app.route("/api/force-song", methods=["POST"])
def api_force_song():
    song = request.form.get("song", "")
    logger.info("API: force-song solicitado: %s", song)
    if _daemon_state["force_song_fn"]:
        ok = _daemon_state["force_song_fn"](song)
        return jsonify({"ok": ok, "song": song})
    return jsonify({"error": "no disponible"}), 503


@app.route("/api/force-master", methods=["POST"])
def api_force_master():
    logger.info("API: force-master solicitado")
    if _daemon_state["force_master_fn"]:
        _daemon_state["force_master_fn"]()
        return jsonify({"ok": True, "master": True})
    return jsonify({"error": "no disponible"}), 503


@app.route("/api/toggle-pause", methods=["POST"])
def api_toggle_pause():
    logger.info("API: toggle-pause solicitado")
    if _daemon_state["toggle_pause_fn"]:
        paused = _daemon_state["toggle_pause_fn"]()
        return jsonify({"ok": True, "paused": paused})
    return jsonify({"error": "no disponible"}), 503


@app.route("/music/<path:filename>")
def serve_music(filename):
    """Sirve archivos de música para que el Master los descargue/stream."""
    music_dir = Path(os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music"))
    try:
        target = (music_dir / filename).resolve()
        if not str(target).startswith(str(music_dir.resolve())):
            abort(403)
        if not target.exists():
            abort(404)
        return send_from_directory(str(music_dir), filename)
    except Exception as e:
        logger.error("Error sirviendo música: %s", e)
        abort(404)


def run_web(host="0.0.0.0", port=8080):
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    run_web()
