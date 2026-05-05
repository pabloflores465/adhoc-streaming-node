#!/usr/bin/env python3
"""
app.py — Panel web y API REST para indicadores y control externo.
"""

import os
import sys
import shutil
import logging
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, request, render_template_string, send_from_directory, send_file, redirect, abort

app = Flask(__name__)

# Referencias inyectadas por node-daemon
_daemon_state = {
    "master": False,
    "current_song": "Ninguna",
    "peers": {},
    "status_fn": None,
    "current_song_fn": None,
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
    * { box-sizing: border-box; }
    body { font-family: sans-serif; background:#111; color:#0f0; padding:1.5rem; margin:0; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap:1rem; }
    .card { background:#1a1a1a; border:1px solid #333; padding:1rem; border-radius:8px; }
    h1 { color:#0ff; margin:0 0 .5rem; font-size:1.4rem; }
    h3 { color:#0ff; margin:.2rem 0 .8rem; font-size:1rem; }
    .role-banner { padding:.5rem 1rem; border-radius:6px; display:inline-block; font-size:1rem; font-weight:bold; }
    .role-master { background:#3a2e00; color:gold; border:1px solid gold; }
    .role-client { background:#1a1a2e; color:#8888ff; border:1px solid #444; }
    .paused-badge { background:#500; color:red; border:1px solid red; padding:.3rem .8rem; border-radius:4px; margin-left:.8rem; font-size:.85rem; }
    .empty-hint { color:#555; font-style:italic; font-size:.85rem; }
    table { width:100%; border-collapse:collapse; margin-top:.5rem; font-size:.85rem; }
    th,td { text-align:left; padding:.3rem .4rem; border-bottom:1px solid #2a2a2a; }
    th { color:#0cf; }
    button { background:#0f0; color:#000; border:none; padding:.45rem .9rem; cursor:pointer; border-radius:4px; font-size:.85rem; font-weight:bold; }
    button:hover { background:#0c0; }
    button.btn-master { background:#c90; color:#000; }
    button.btn-master:hover { background:#fa0; }
    button.btn-pause { background:#444; color:#ccc; }
    button.btn-pause:hover { background:#666; }
    input[type=text] { padding:.4rem .6rem; width:65%; background:#222; color:#0f0; border:1px solid #444; border-radius:4px; font-size:.85rem; }
    .self-node { color:#0f0; font-weight:bold; }
    .peer-node { color:#0af; font-weight:bold; }
    .player-card { background:#0d1a0d; border:2px solid #0a0; }
    .now-playing { font-size:1.1rem; color:#0f0; margin:.5rem 0; word-break:break-all; }
    .now-playing span { color:#ff0; font-weight:bold; }
    audio { width:100%; margin-top:.6rem; accent-color:#0f0; }
    .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
    .dot-playing { background:#0f0; animation: pulse 1.2s infinite; }
    .dot-idle    { background:#555; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
    .song-btn { font-size:.75rem; padding:.2rem .5rem; margin:.15rem; background:#0f0; color:#000; border:none; border-radius:3px; cursor:pointer; }
    .song-btn:hover { background:#0c0; }
    .song-btn.remote { background:#07f; color:#fff; }
    .song-btn.remote:hover { background:#05c; }
    .song-btn:disabled { background:#444; color:#888; cursor:wait; }
    .header-row { display:flex; align-items:center; gap:1rem; flex-wrap:wrap; margin-bottom:1rem; }
    .cell-tag { color:#555; font-size:.8rem; }
    #dl-status { font-size:.8rem; color:#fa0; margin-top:.4rem; min-height:1rem; }
  </style>
</head>
<body>
  <div class="header-row">
    <h1>AD-HOC Node — {{ node_id }}</h1>
    <span class="role-banner {{ 'role-master' if is_master else 'role-client' }}" id="role-banner">
      {% if is_master %}★ MASTER{% else %}◎ Cliente{% endif %}
    </span>
    {% if paused %}<span class="paused-badge" id="paused-badge">⏸ PAUSADO</span>{% endif %}
    <span class="cell-tag">Celda: <code>{{ cell_id }}</code></span>
  </div>

  <!-- Player -->
  <div class="card player-card" style="margin-bottom:1rem">
    <h3>Reproducción</h3>
    <p id="playing-line" class="now-playing">
      <span class="status-dot {% if current_song != 'Ninguna' %}dot-playing{% else %}dot-idle{% endif %}" id="status-dot"></span>
      Reproduciendo: <span id="current-song-label">{{ current_song }}</span>
    </p>
    <audio id="player" controls preload="none"></audio>
    <p style="color:#555; font-size:.75rem; margin-top:.4rem" id="player-hint">
      {% if is_master %}Fuente: este nodo (master){% else %}Fuente: master de la red{% endif %}
    </p>
  </div>

  <div class="grid">
    <!-- Control -->
    <div class="card">
      <h3>{% if is_master %}Control de transmisión{% else %}Solicitar canción{% endif %}</h3>
      <p style="font-size:.85rem"><strong>Tasa TX:</strong> {{ tx_rate }}</p>

      <form id="force-form" style="display:flex;gap:.4rem;margin-top:.5rem;flex-wrap:wrap">
        <input type="text" id="force-input" placeholder="nombre_cancion.mp3">
        <button type="submit" id="force-btn">{% if is_master %}Forzar{% else %}Solicitar{% endif %}</button>
      </form>

      <div id="dl-status"></div>

      {% if not is_master %}
      <form action="/api/force-master" method="post" style="margin-top:.5rem">
        <button type="submit" class="btn-master">Tomar control (Master)</button>
      </form>
      {% endif %}

      <form action="/api/toggle-pause" method="post" style="margin-top:.5rem">
        <button type="submit" class="btn-pause">{% if paused %}▶ Reanudar{% else %}⏸ Pausar{% endif %}</button>
      </form>

      <p style="margin-top:1rem;font-size:.85rem;color:#0cf"><strong>Canciones en la red:</strong></p>
      <div id="song-buttons" style="display:flex;flex-wrap:wrap;gap:.2rem;margin-top:.3rem">
        {% for song in all_network_songs %}
        <button class="song-btn {% if not song.is_local %}remote{% endif %}"
                onclick="requestSong('{{ song.name }}', {{ song.is_local|tojson }}, '{{ song.peer_ip }}')">
          {{ song.name }}{% if not song.is_local %} [{{ song.node_id[:6] }}]{% endif %}
        </button>
        {% else %}
        <span class="empty-hint">Sin canciones en la red aún.</span>
        {% endfor %}
      </div>
    </div>

    <!-- Peers -->
    <div class="card">
      <h3>Peers activos (<span id="peer-count">{{ peer_count }}</span>)</h3>
      <div id="peers-table">
        {% if peers %}
        <table>
          <tr><th>Node ID</th><th>IP</th><th>Score</th><th>Rol</th><th>Songs</th></tr>
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
        <p class="empty-hint">Sin peers. Aparecen con heartbeats (cada 3s).</p>
        {% endif %}
      </div>
    </div>

    <!-- Inventario -->
    <div class="card">
      <h3>Inventario por nodo</h3>
      <div id="inventory-list">
        <p><span class="self-node">{{ node_id }}</span> <span style="color:#555">(este nodo):</span></p>
        <ul style="font-size:.8rem;padding-left:1rem;margin:.3rem 0">
          {% for s in local_songs %}<li>{{ s }}</li>
          {% else %}<li class="empty-hint">Sin canciones locales</li>{% endfor %}
        </ul>
        {% for nid, info in peers.items() %}
        <p style="margin-top:.5rem"><span class="peer-node">{{ nid }}</span> <span style="color:#555">({{ info.ip }}):</span></p>
        <ul style="font-size:.8rem;padding-left:1rem;margin:.3rem 0">
          {% for s in info.songs %}<li>{{ s }}</li>
          {% else %}<li class="empty-hint">Sin canciones reportadas</li>{% endfor %}
        </ul>
        {% endfor %}
      </div>
    </div>

    <!-- Señal -->
    <div class="card">
      <h3>Señal y Modulación</h3>
      <p style="font-size:.85rem"><strong>Modulación:</strong> {{ modulation }}</p>
      {% if signal_levels %}
      <table>
        <tr><th>MAC</th><th>Señal</th></tr>
        {% for mac, sig in signal_levels.items() %}
        <tr><td style="font-size:.8rem">{{ mac }}</td><td>{{ sig }}</td></tr>
        {% endfor %}
      </table>
      {% else %}
      <p class="empty-hint">Sin estaciones IBSS detectadas aún.</p>
      {% endif %}
    </div>

    <!-- Sistema -->
    <div class="card">
      <h3>Sistema</h3>
      <p style="font-size:.85rem" id="sys-cpu">CPU: {{ system.cpu_percent }}%</p>
      <p style="font-size:.85rem" id="sys-ram">RAM libre: {{ system.ram_available_mb }} MB</p>
      <p style="font-size:.85rem" id="sys-load">Load avg: {{ system.load_avg }}</p>
    </div>
  </div>

<script>
  const IS_MASTER = {{ 'true' if is_master else 'false' }};
  const NODE_ID   = "{{ node_id }}";
  let currentSong      = "{{ current_song }}";
  let masterIp         = null;
  let pendingSong      = null;
  let pendingTimer     = null;

  const audio     = document.getElementById('player');
  const songLabel = document.getElementById('current-song-label');
  const statusDot = document.getElementById('status-dot');
  const dlStatus  = document.getElementById('dl-status');

  // Init master IP from server-rendered peers
  {% for nid, info in peers.items() %}
    {% if info.is_master %}masterIp = "{{ info.ip }}";{% endif %}
  {% endfor %}

  function streamUrl() {
    if (IS_MASTER) return '/stream';
    if (masterIp)  return 'http://' + masterIp + ':8080/stream';
    return '';
  }

  function reloadPlayer(song) {
    const src = streamUrl();
    if (!src) return;
    // Cache-bust so the browser always makes a new request even if base URL is identical
    audio.src = src + '?t=' + Date.now();
    audio.setAttribute('data-song', song);
    audio.load();
    audio.play().catch(() => {});
  }

  function setAudioSrcIfChanged(song) {
    const src = streamUrl();
    if (!src) return;
    if (audio.getAttribute('data-song') !== song) {
      const wasPlaying = !audio.paused;
      audio.src = src;
      audio.setAttribute('data-song', song);
      if (wasPlaying) audio.play().catch(() => {});
    }
  }

  // Build a song button element
  function makeSongBtn(song) {
    const btn = document.createElement('button');
    btn.className = 'song-btn' + (song.is_local ? '' : ' remote');
    btn.textContent = song.name + (song.is_local ? '' : ' [' + song.node_id.slice(0,6) + ']');
    btn.dataset.song   = song.name;
    btn.dataset.local  = song.is_local ? '1' : '0';
    btn.dataset.peerIp = song.peer_ip || '';
    btn.onclick = () => requestSong(song.name, song.is_local, song.peer_ip || '');
    return btn;
  }

  function rebuildSongButtons(songs) {
    const container = document.getElementById('song-buttons');
    if (!songs || songs.length === 0) {
      container.innerHTML = '<span class="empty-hint">Sin canciones en la red aún.</span>';
      return;
    }
    // Preserve buttons that already exist (avoid flicker)
    const existing = {};
    container.querySelectorAll('.song-btn').forEach(b => { existing[b.dataset.song] = b; });
    container.innerHTML = '';
    songs.forEach(song => {
      if (existing[song.name]) {
        container.appendChild(existing[song.name]);
      } else {
        container.appendChild(makeSongBtn(song));
      }
    });
  }

  function setPending(name) {
    pendingSong = name;
    if (pendingTimer) clearTimeout(pendingTimer);
    // Auto-clear pending after 12s in case master never confirms
    pendingTimer = setTimeout(() => { pendingSong = null; }, 12000);
  }

  async function requestSong(name, isLocal, peerIp) {
    setPending(name);
    dlStatus.textContent = '';

    // If remote song, download it first
    if (!isLocal && peerIp) {
      dlStatus.textContent = 'Descargando ' + name + ' del peer ' + peerIp + '...';
      // Disable all buttons while downloading
      document.querySelectorAll('.song-btn').forEach(b => b.disabled = true);
      try {
        const fd = new FormData();
        fd.append('song', name);
        fd.append('peer_ip', peerIp);
        const res  = await fetch('/api/download-song', { method: 'POST', body: fd });
        const data = await res.json();
        if (!data.ok) {
          dlStatus.textContent = 'Error al descargar: ' + (data.error || 'desconocido');
          pendingSong = null;
          document.querySelectorAll('.song-btn').forEach(b => b.disabled = false);
          return;
        }
        dlStatus.textContent = 'Descargado. Reproduciendo...';
      } catch(e) {
        dlStatus.textContent = 'Error de red al descargar.';
        pendingSong = null;
        document.querySelectorAll('.song-btn').forEach(b => b.disabled = false);
        return;
      }
      document.querySelectorAll('.song-btn').forEach(b => b.disabled = false);
    }

    // Force the song on the master
    const fd2 = new FormData();
    fd2.append('song', name);
    await fetch('/api/force-song', { method: 'POST', body: fd2 });
    document.getElementById('force-input').value = '';

    // Immediately reload player to new stream
    currentSong = name;
    songLabel.textContent = name;
    statusDot.className = 'status-dot dot-playing';
    reloadPlayer(name);

    setTimeout(() => { dlStatus.textContent = ''; }, 3000);
  }

  document.getElementById('force-form').addEventListener('submit', e => {
    e.preventDefault();
    const val = document.getElementById('force-input').value.trim();
    if (!val) return;
    // Treat typed songs as local (master will resolve via network if not found locally)
    requestSong(val, true, '');
  });

  function esc(s) {
    return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function rebuildInventory(data) {
    const peers = data.peers || {};
    const localSongs = data.local_songs || [];
    let html = `<p><span class="self-node">${esc(data.node_id || NODE_ID)}</span> <span style="color:#555">(este nodo):</span></p>`;
    html += '<ul style="font-size:.8rem;padding-left:1rem;margin:.3rem 0">';
    if (localSongs.length) localSongs.forEach(s => { html += `<li>${esc(s)}</li>`; });
    else html += '<li class="empty-hint">Sin canciones locales</li>';
    html += '</ul>';
    for (const [nid, info] of Object.entries(peers)) {
      html += `<p style="margin-top:.5rem"><span class="peer-node">${esc(nid)}</span> <span style="color:#555">(${esc(info.ip || '')}):</span></p>`;
      html += '<ul style="font-size:.8rem;padding-left:1rem;margin:.3rem 0">';
      const songs = info.songs || [];
      if (songs.length) songs.forEach(s => { html += `<li>${esc(s)}</li>`; });
      else html += '<li class="empty-hint">Sin canciones reportadas</li>';
      html += '</ul>';
    }
    document.getElementById('inventory-list').innerHTML = html;
  }

  async function poll() {
    try {
      const res  = await fetch('/api/status', { cache: 'no-store' });
      const data = await res.json();
      const song  = data.current_song || 'Ninguna';
      const peers = data.peers || {};

      // Find master IP
      for (const [nid, info] of Object.entries(peers)) {
        if (info.is_master) { masterIp = info.ip; break; }
      }

      // Update song label & dot (don't overwrite while a click is pending)
      if (!pendingSong) {
        songLabel.textContent = song;
        statusDot.className = (song && song !== 'Ninguna')
          ? 'status-dot dot-playing' : 'status-dot dot-idle';
      }

      // Update audio based on what the master reports
      if (song && song !== 'Ninguna') {
        if (pendingSong) {
          // We requested a change — ignore poll until master confirms it
          if (song === pendingSong) {
            clearTimeout(pendingTimer);
            pendingSong = null;
            currentSong = song;
            // Don't reload — we already reloaded on click
          }
          // else: master hasn't switched yet, keep waiting
        } else if (song !== currentSong) {
          // Master changed song externally (next track, other node, etc.)
          currentSong = song;
          reloadPlayer(song);
        } else if (!audio.getAttribute('data-song')) {
          // First load — set src without forcing play
          setAudioSrcIfChanged(song);
        }
      }

      // Peer count & table
      const peerKeys = Object.keys(peers);
      document.getElementById('peer-count').textContent = peerKeys.length;
      let html = '';
      if (peerKeys.length) {
        html = '<table><tr><th>Node ID</th><th>IP</th><th>Score</th><th>Rol</th><th>Songs</th></tr>';
        for (const [nid, info] of Object.entries(peers)) {
          const role = info.is_master ? '<span style="color:gold">Master</span>' : 'Cliente';
          html += `<tr><td>${nid}</td><td>${info.ip}</td><td>${info.score}</td><td>${role}</td><td>${(info.songs||[]).length}</td></tr>`;
        }
        html += '</table>';
      } else {
        html = '<p class="empty-hint">Sin peers. Aparecen con heartbeats (cada 3s).</p>';
      }
      document.getElementById('peers-table').innerHTML = html;

      // Rebuild song buttons from live network data
      if (data.all_network_songs) {
        rebuildSongButtons(data.all_network_songs);
      }

      rebuildInventory(data);

      // System
      if (data.system) {
        document.getElementById('sys-cpu').textContent  = 'CPU: ' + data.system.cpu_percent + '%';
        document.getElementById('sys-ram').textContent  = 'RAM libre: ' + data.system.ram_available_mb + ' MB';
        document.getElementById('sys-load').textContent = 'Load avg: ' + data.system.load_avg;
      }
    } catch(e) { /* red no disponible */ }
  }

  // Init player on load
  if (currentSong && currentSong !== 'Ninguna') {
    setAudioSrcIfChanged(currentSong);
  }

  poll();
  setInterval(poll, 3000);
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
        resp = jsonify(_daemon_state["status_fn"]())
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
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


@app.route("/api/download-song", methods=["POST"])
def api_download_song():
    """Descarga una canción de un peer y la guarda en la carpeta local de música."""
    song    = request.form.get("song", "").strip()
    peer_ip = request.form.get("peer_ip", "").strip()
    if not song or not peer_ip:
        return jsonify({"error": "song y peer_ip requeridos"}), 400
    if "/" in song or ".." in song:
        return jsonify({"error": "nombre de canción inválido"}), 400

    music_dir = Path(os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music"))
    dest = music_dir / song
    if dest.exists():
        logger.info("Canción ya existe localmente: %s", song)
        return jsonify({"ok": True, "cached": True})

    url = f"http://{peer_ip}:8080/music/{song}"
    tmp = dest.with_suffix(".tmp")
    try:
        logger.info("Descargando %s desde %s", song, peer_ip)
        req = urllib.request.Request(url, headers={"User-Agent": "adhoc-node/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        tmp.rename(dest)
        logger.info("Canción descargada exitosamente: %s", song)
        return jsonify({"ok": True})
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        logger.error("Error descargando %s de %s: %s", song, peer_ip, e)
        return jsonify({"error": str(e)}), 500


@app.route("/stream")
def stream_audio():
    """Sirve la canción actual como HTTP audio para el player del browser."""
    if _daemon_state.get("current_song_fn"):
        song = _daemon_state["current_song_fn"]()
    elif _daemon_state["status_fn"]:
        song = _daemon_state["status_fn"]().get("current_song", "Ninguna")
    else:
        abort(503)
    if not song or song in ("Ninguna",) or song.startswith("Stream multicast"):
        abort(404)

    music_dir = Path(os.environ.get("ADHOC_MUSIC", "/opt/adhoc-node/music"))
    song_path = music_dir / song
    if song_path.exists():
        mime = "audio/ogg" if song.endswith(".ogg") else "audio/mpeg"
        return send_file(str(song_path), mimetype=mime, conditional=True)

    # Canción remota: redirigir al peer que la tiene
    if _daemon_state["status_fn"]:
        status_data = _daemon_state["status_fn"]()
        for nid, info in status_data.get("peers", {}).items():
            if song in info.get("songs", []):
                peer_ip = info.get("ip", "")
                if peer_ip and peer_ip != "0.0.0.0":
                    return redirect(f"http://{peer_ip}:8080/music/{song}")
    abort(404)


@app.route("/music/<path:filename>")
def serve_music(filename):
    """Sirve archivos de música locales (para que otros nodos los descarguen)."""
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
