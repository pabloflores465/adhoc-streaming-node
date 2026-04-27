#!/usr/bin/env python3
"""
test_integration.py — Simulación completa del flujo AD-HOC streaming.

Escenarios:
  1. Nodo A (Master) + Nodo B (Cliente). Streaming activo.
  2. Nodo A desconecta → B pierde Master → B entra en PAUSA.
  3. Nodo B se convierte en Master → reproduce otra canción.
  4. Nodo A reconecta → ambos ven heartbeats → A tiene mejor score → A gana.
  5. B se rinde, todos reanudan automáticamente (si misma canción) o en pausa (si cambió).

Ejecutar:  python3 test_integration.py
"""

import os
import sys
import time
import json
import socket
import struct
import threading
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ─── Configuración del simulador ────────────────────────────────────────────
os.environ["ADHOC_MULTI"] = "239.255.99.99"
os.environ["ADHOC_NET"] = "10.254.0"

TEST_PORT_BASE = 55000


def _pick_port():
    """Devuelve un puerto UDP libre."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class SimulatedNode:
    """
    Nodo virtual que simula el comportamiento del daemon sin ffmpeg/mpv.
    Usa sockets UDP reales para heartbeats y un contador lógico para streaming.
    """

    def __init__(self, node_id: str, score: int, songs: list, port: int = None):
        self.node_id = node_id
        self.score = score
        self.songs = songs
        self.port = port or _pick_port()
        self.is_master = False
        self.paused = False
        self.current_song = "Ninguna"
        self.previous_song = "Ninguna"
        self.forced_song = None
        self.peers = {}  # nid -> {ip, score, is_master, last_seen, songs}
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        self.sock.bind(("127.0.0.1", self.port))
        self._running = True
        self._threads = []

        # Métricas de test
        self.events = []
        self._log(f"[{node_id}] Iniciado en puerto {self.port} con score {score}")

    def _log(self, msg: str):
        print(f"  {msg}")
        self.events.append(msg)

    def start(self):
        t_recv = threading.Thread(target=self._receiver_loop, daemon=True)
        t_hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t_logic = threading.Thread(target=self._logic_loop, daemon=True)
        t_recv.start()
        t_hb.start()
        t_logic.start()
        self._threads = [t_recv, t_hb, t_logic]

    def stop(self):
        self._running = False
        self.sock.close()
        for t in self._threads:
            t.join(timeout=2)
        self._log(f"[{self.node_id}] Detenido")

    def _send_json(self, target_port: int, msg: dict):
        try:
            self.sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", target_port))
        except Exception:
            pass

    def _broadcast_to_all(self, msg: dict, ports: list):
        for p in ports:
            if p != self.port:
                self._send_json(p, msg)

    def _receiver_loop(self):
        self.sock.settimeout(0.5)
        while self._running:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                msg_type = msg.get("type")
                nid = msg.get("node_id")
                if nid == self.node_id:
                    continue

                if msg_type == "heartbeat":
                    with self.lock:
                        self.peers[nid] = {
                            "ip": msg.get("ip", addr[0]),
                            "score": msg.get("score", 0),
                            "is_master": msg.get("is_master", False),
                            "songs": msg.get("songs", []),
                            "last_seen": time.time(),
                        }
                elif msg_type == "song_request":
                    song = msg.get("song_name", "")
                    with self.lock:
                        if self.is_master:
                            self._log(f"[{self.node_id}] RECIBIÓ song_request: {song}")
                            self.forced_song = song
                elif msg_type == "ip_reassign":
                    if msg.get("target_node_id") == self.node_id:
                        self._log(f"[{self.node_id}] IP reasignada a {msg.get('new_ip')}")

            except socket.timeout:
                continue
            except Exception:
                continue

    def _heartbeat_loop(self):
        while self._running:
            msg = {
                "type": "heartbeat",
                "node_id": self.node_id,
                "timestamp": time.time(),
                "score": self.score,
                "ip": f"10.254.0.{self.port % 256}",
                "is_master": self.is_master,
                "songs": self.songs,
            }
            # Broadcast a todos los puertos conocidos (peers)
            with self.lock:
                ports = [info.get("_port", self.port) for info in self.peers.values()]
            # También enviamos a un puerto fijo para descubrimiento inicial
            # En simulación real usamos explícito
            time.sleep(0.5)

    def _cleanup_peers(self, timeout: float = 3.0):
        now = time.time()
        with self.lock:
            dead = [nid for nid, info in self.peers.items() if now - info.get("last_seen", 0) > timeout]
            for nid in dead:
                del self.peers[nid]
                self._log(f"[{self.node_id}] Peer {nid} muerto (timeout)")

    def _am_i_master(self) -> bool:
        with self.lock:
            if not self.peers:
                return True
            for info in self.peers.values():
                if info.get("score", 0) > self.score:
                    return False
            return True

    def _another_master_with_higher_score(self) -> bool:
        with self.lock:
            for info in self.peers.values():
                if info.get("is_master") and info.get("score", 0) > self.score:
                    return True
            return False

    def _resolve_song(self, song_name: str):
        for s in self.songs:
            if s == song_name:
                return (True, None)
        with self.lock:
            for nid, info in self.peers.items():
                if song_name in info.get("songs", []):
                    return (False, info.get("ip"))
        return (None, None)

    def _logic_loop(self):
        while self._running:
            time.sleep(0.3)
            self._cleanup_peers(timeout=3.0)

            with self.lock:
                forced = self.forced_song
                self.forced_song = None

            # Detectar otro Master con mejor score
            if self._another_master_with_higher_score():
                with self.lock:
                    if self.is_master:
                        self._log(f"[{self.node_id}] RINDIENDO ante Master con mejor score")
                        self.is_master = False
                        self.previous_song = self.current_song
                        self.paused = True  # PAUSA automática al perder Master

            # Evaluar si somos master
            master_now = self._am_i_master()
            with self.lock:
                became_master = master_now and not self.is_master
                lost_master = not master_now and self.is_master
                self.is_master = master_now

            if became_master:
                self._log(f"[{self.node_id}] → MASTER (pick next song)")
                # Simular sniff_multicast (siempre silencio en simulación limpia)
                self._pick_and_stream()
                continue

            if lost_master:
                self._log(f"[{self.node_id}] Dejó de ser master → cliente")
                with self.lock:
                    self.previous_song = self.current_song
                continue

            if self.is_master:
                if forced:
                    local, remote = self._resolve_song(forced)
                    if local is not None:
                        self._start_streaming(forced, source="local")
                    elif remote is not None:
                        self._start_streaming(forced, source="relay")
                    else:
                        self._log(f"[{self.node_id}] Canción '{forced}' no encontrada")
                # En simulación el stream dura "para siempre" hasta que otro lo cambie
            else:
                # Cliente: si no pausado, "reproduce" el stream
                with self.lock:
                    if self.paused:
                        continue
                    # Detectar si el Master actual cambió canción
                    current_master_song = "Ninguna"
                    for info in self.peers.values():
                        if info.get("is_master"):
                            # En simulación no tenemos canción del master via heartbeat
                            # pero simulamos que si cambia entramos en pausa
                            pass

    def _pick_and_stream(self):
        """Elige canción aleatoria de todo el inventario."""
        all_songs = list(self.songs)
        with self.lock:
            for info in self.peers.values():
                all_songs.extend(info.get("songs", []))
        if not all_songs:
            return
        song = all_songs[0]  # Determinista para test
        self._start_streaming(song, source="pick")

    def _start_streaming(self, song: str, source: str):
        with self.lock:
            if self.current_song == song:
                return  # Ya está sonando
            self.current_song = song
        self._log(f"[{self.node_id}] ▶ STREAMING: {song} ({source})")

    def request_song(self, song_name: str, target_ports: list):
        """Solicitar canción vía broadcast."""
        msg = {
            "type": "song_request",
            "node_id": self.node_id,
            "song_name": song_name,
            "timestamp": time.time(),
        }
        self._broadcast_to_all(msg, target_ports)
        self._log(f"[{self.node_id}] SOLICITA canción: {song_name}")

    def toggle_pause(self):
        with self.lock:
            self.paused = not self.paused
            state = "PAUSADO" if self.paused else "REPRODUCIENDO"
        self._log(f"[{self.node_id}] {state}")

    def status(self) -> dict:
        with self.lock:
            return {
                "node_id": self.node_id,
                "is_master": self.is_master,
                "paused": self.paused,
                "current_song": self.current_song,
                "peers": list(self.peers.keys()),
                "score": self.score,
            }


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DE INTEGRACIÓN
# ═════════════════════════════════════════════════════════════════════════════

def wait_for(condition, timeout=5.0, interval=0.2):
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    return False


def test_scenario_1_basic_master_client():
    print("\n" + "=" * 70)
    print(" ESCENARIO 1: Nodo A (Master, score 500) + Nodo B (Cliente, score 300)")
    print("=" * 70)

    node_a = SimulatedNode("A", score=500, songs=["song_A1.mp3", "song_A2.mp3"])
    node_b = SimulatedNode("B", score=300, songs=["song_B1.mp3"])

    # Hacemos que se conozcan mutuamente
    node_a.start()
    node_b.start()

    # Enviamos heartbeats cruzados manualmente para bootstrap
    for _ in range(5):
        msg_a = {"type": "heartbeat", "node_id": "A", "score": 500, "ip": "10.0.0.1",
                 "is_master": False, "songs": node_a.songs, "timestamp": time.time()}
        msg_b = {"type": "heartbeat", "node_id": "B", "score": 300, "ip": "10.0.0.2",
                 "is_master": False, "songs": node_b.songs, "timestamp": time.time()}
        node_a.sock.sendto(json.dumps(msg_b).encode(), ("127.0.0.1", node_a.port))
        node_b.sock.sendto(json.dumps(msg_a).encode(), ("127.0.0.1", node_b.port))
        time.sleep(0.3)

    # Esperar que A se convierta en Master
    assert wait_for(lambda: node_a.is_master), "A debería ser Master"
    assert wait_for(lambda: not node_b.is_master), "B no debería ser Master"
    print(f"\n✅ A es Master, B es Cliente")

    # B solicita canción de A
    node_b.request_song("song_A1.mp3", [node_a.port])
    time.sleep(1.0)
    assert node_a.current_song == "song_A1.mp3", f"A debería reproducir song_A1, tiene {node_a.current_song}"
    print(f"✅ B solicitó song_A1.mp3 → A la está reproduciendo")

    node_a.stop()
    node_b.stop()
    print("✅ ESCENARIO 1 PASADO")


def test_scenario_2_disconnect_pause_reconnect():
    print("\n" + "=" * 70)
    print(" ESCENARIO 2: A desconecta → B pausa → A reconecta → A gana (mejor score)")
    print("=" * 70)

    node_a = SimulatedNode("A", score=500, songs=["song_A1.mp3"])
    node_b = SimulatedNode("B", score=300, songs=["song_B1.mp3"])

    node_a.start()
    node_b.start()

    # Fase 1: Conexión inicial
    for _ in range(5):
        msg_a = {"type": "heartbeat", "node_id": "A", "score": 500, "ip": "10.0.0.1",
                 "is_master": True, "songs": node_a.songs, "timestamp": time.time()}
        msg_b = {"type": "heartbeat", "node_id": "B", "score": 300, "ip": "10.0.0.2",
                 "is_master": False, "songs": node_b.songs, "timestamp": time.time()}
        node_a.sock.sendto(json.dumps(msg_b).encode(), ("127.0.0.1", node_a.port))
        node_b.sock.sendto(json.dumps(msg_a).encode(), ("127.0.0.1", node_b.port))
        time.sleep(0.3)

    assert wait_for(lambda: node_a.is_master)
    node_a._start_streaming("song_A1.mp3", "initial")
    print(f"\n  Estado inicial: A=Master({node_a.current_song}), B=Cliente(paused={node_b.paused})")

    # Fase 2: A "desconecta" (dejamos de enviar heartbeats de A a B)
    print("\n  >>> A se desconecta...")
    # B dejará de ver a A tras timeout (3s en simulación)
    time.sleep(4.0)

    # B debe detectar que A murió y auto-promoverse
    assert wait_for(lambda: "A" not in node_b.peers, timeout=5), "B debería haber limpiado a A"
    print(f"  B peers después de timeout: {list(node_b.peers.keys())}")

    # B se convierte en Master (0 peers = soy Master)
    assert wait_for(lambda: node_b.is_master, timeout=3), "B debería ser Master tras perder a A"
    print(f"  ✅ B se convirtió en Master (A desapareció)")

    # B reproduce otra canción
    node_b._start_streaming("song_B1.mp3", "new_master")
    print(f"  B ahora streaming: {node_b.current_song}")

    # Fase 3: A "reconecta" (enviamos heartbeats de A de nuevo)
    print("\n  >>> A reconecta...")
    for _ in range(10):
        msg_a = {"type": "heartbeat", "node_id": "A", "score": 500, "ip": "10.0.0.1",
                 "is_master": True, "songs": node_a.songs, "timestamp": time.time()}
        # A debe ver que B es Master y rendirse (porque B tiene score 300 < 500? No, A tiene mejor score)
        # Pero B debe ver que A (con score 500) es Master y rendirse
        node_b.sock.sendto(json.dumps(msg_a).encode(), ("127.0.0.1", node_b.port))
        # También B envía heartbeat a A para que A sepa que existe
        msg_b = {"type": "heartbeat", "node_id": "B", "score": 300, "ip": "10.0.0.2",
                 "is_master": True, "songs": node_b.songs, "timestamp": time.time()}
        node_a.sock.sendto(json.dumps(msg_b).encode(), ("127.0.0.1", node_a.port))
        time.sleep(0.3)

    # Verificar: A debería seguir siendo Master (mejor score)
    # B debería rendirse (ve a A con score 500 > 300 y is_master=True)
    time.sleep(1.0)
    print(f"\n  Estado tras reconexión:")
    print(f"    A: master={node_a.is_master}, song={node_a.current_song}")
    print(f"    B: master={node_b.is_master}, song={node_b.current_song}, paused={node_b.paused}")

    # B debería haberse rendido (ya no es Master)
    assert not node_b.is_master, f"B debería haberse rendido, is_master={node_b.is_master}"
    print(f"  ✅ B se rindió ante A (score 500 > 300)")

    # B debería estar en pausa (cambio de Master con canción diferente)
    assert node_b.paused, f"B debería estar en pausa tras cambio de Master"
    print(f"  ✅ B está en PAUSA automática (canción cambió de {node_b.previous_song} a {node_a.current_song})")

    # Fase 4: B presiona Play
    print("\n  >>> B presiona Play...")
    node_b.toggle_pause()
    assert not node_b.paused
    print(f"  ✅ B reanudó reproducción")

    node_a.stop()
    node_b.stop()
    print("✅ ESCENARIO 2 PASADO")


def test_scenario_3_two_masters_meet():
    print("\n" + "=" * 70)
    print(" ESCENARIO 3: Dos Masters aislados se encuentran → gana mejor score")
    print("=" * 70)

    node_a = SimulatedNode("A", score=800, songs=["song_A.mp3"])
    node_b = SimulatedNode("B", score=600, songs=["song_B.mp3"])

    node_a.start()
    node_b.start()

    # Ambos empiezan como Master (aislados, 0 peers)
    time.sleep(1.0)
    assert node_a.is_master, "A debería ser Master (0 peers)"
    assert node_b.is_master, "B debería ser Master (0 peers)"
    node_a._start_streaming("song_A.mp3", "solo")
    node_b._start_streaming("song_B.mp3", "solo")
    print(f"\n  Inicio: A=Master({node_a.current_song}), B=Master({node_b.current_song})")

    # Se "encuentran" (envían heartbeats mutuos)
    print("\n  >>> A y B se encuentran...")
    for _ in range(10):
        msg_a = {"type": "heartbeat", "node_id": "A", "score": 800, "ip": "10.0.0.1",
                 "is_master": True, "songs": node_a.songs, "timestamp": time.time()}
        msg_b = {"type": "heartbeat", "node_id": "B", "score": 600, "ip": "10.0.0.2",
                 "is_master": True, "songs": node_b.songs, "timestamp": time.time()}
        node_b.sock.sendto(json.dumps(msg_a).encode(), ("127.0.0.1", node_b.port))
        node_a.sock.sendto(json.dumps(msg_b).encode(), ("127.0.0.1", node_a.port))
        time.sleep(0.3)

    time.sleep(1.0)
    print(f"\n  Estado tras encuentro:")
    print(f"    A: master={node_a.is_master}, song={node_a.current_song}")
    print(f"    B: master={node_b.is_master}, song={node_b.current_song}, paused={node_b.paused}")

    # A debería seguir siendo Master (score 800 > 600)
    assert node_a.is_master, "A debería seguir siendo Master (mejor score)"
    # B debería haberse rendido
    assert not node_b.is_master, "B debería haberse rendido"
    # B debería estar en pausa (canción diferente)
    assert node_b.paused, "B debería estar en pausa"
    print(f"  ✅ A (score 800) ganó, B (score 600) se rindió y pausó")

    node_a.stop()
    node_b.stop()
    print("✅ ESCENARIO 3 PASADO")


def test_scenario_4_song_request_from_client():
    print("\n" + "=" * 70)
    print(" ESCENARIO 4: Cliente solicita canción remota → Master la reproduce")
    print("=" * 70)

    node_a = SimulatedNode("A", score=500, songs=["song_A1.mp3", "song_A2.mp3"])
    node_b = SimulatedNode("B", score=300, songs=["song_B1.mp3"])
    node_c = SimulatedNode("C", score=200, songs=["song_C1.mp3"])

    nodes = [node_a, node_b, node_c]
    for n in nodes:
        n.start()

    # Bootstrap: todos se conocen
    ports = [n.port for n in nodes]
    for _ in range(5):
        for n in nodes:
            for other in nodes:
                if other.node_id != n.node_id:
                    msg = {"type": "heartbeat", "node_id": n.node_id, "score": n.score,
                           "ip": f"10.0.0.{n.port % 256}", "is_master": False,
                           "songs": n.songs, "timestamp": time.time()}
                    other.sock.sendto(json.dumps(msg).encode(), ("127.0.0.1", other.port))
        time.sleep(0.3)

    assert wait_for(lambda: node_a.is_master), "A debería ser Master"
    print(f"\n  A es Master. Canciones disponibles en red:")
    print(f"    A: {node_a.songs}")
    print(f"    B: {node_b.songs}")
    print(f"    C: {node_c.songs}")

    # C (cliente) solicita canción de B
    print(f"\n  >>> C solicita 'song_B1.mp3' (de B)...")
    node_c.request_song("song_B1.mp3", ports)
    time.sleep(1.5)

    assert node_a.current_song == "song_B1.mp3", f"A debería reproducir song_B1, tiene {node_a.current_song}"
    print(f"  ✅ Master A recibió solicitud y reproduce song_B1.mp3 (relay desde B)")

    # C solicita canción que YA está sonando → debería ignorar
    print(f"\n  >>> C vuelve a solicitar 'song_B1.mp3' (ya sonando)...")
    node_c.request_song("song_B1.mp3", ports)
    time.sleep(0.5)
    # No debería haber cambio
    assert node_a.current_song == "song_B1.mp3"
    print(f"  ✅ Master ignoró solicitud duplicada (ya está sonando)")

    for n in nodes:
        n.stop()
    print("✅ ESCENARIO 4 PASADO")


if __name__ == "__main__":
    print("\n" + "#" * 70)
    print("#  SIMULACIÓN COMPLETA AD-HOC STREAMING")
    print("#  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("#" * 70)

    try:
        test_scenario_1_basic_master_client()
        test_scenario_2_disconnect_pause_reconnect()
        test_scenario_3_two_masters_meet()
        test_scenario_4_song_request_from_client()

        print("\n" + "🎉" * 35)
        print("  TODOS LOS ESCENARIOS PASARON")
        print("🎉" * 35)
    except AssertionError as e:
        print(f"\n❌ FALLA: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
