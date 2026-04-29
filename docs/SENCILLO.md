# Guía Sencilla — Red de Música Inalámbrica AD-HOC

Esta guía explica el proyecto sin términos complicados: qué es, cómo se usa y cómo comprobar que funciona.

---

## ¿Qué es esto?

Imagina que tienes varias laptops en un salón de clases. Normalmente, para que se comuniquen necesitas un router WiFi en el centro. Este proyecto hace algo diferente: **las laptops crean su propia red entre ellas, sin router**, como si se hablaran directamente.

Una vez conectadas, una laptop (el "Master") elige una canción al azar y la transmite a todas las demás al mismo tiempo, como una estación de radio que solo existe dentro del salón.

Cada laptop tiene sus propias 25 canciones que solo ella conoce, pero el Master puede elegir cualquier canción de cualquier laptop de la red.

### ¿Qué pasa si una laptop se aleja demasiado?

Si una laptop se va tan lejos que ya no alcanza la señal de las demás, no se queda sola — crea su propia mini-red y se convierte en el Master de ese grupo. Cuando vuelve al rango, se reintegra a la red principal automáticamente.

---

## Lo que necesitas antes de empezar

- Una laptop con Fedora 43 instalado (puede ser en USB booteable)
- La laptop debe tener tarjeta WiFi
- Conexión a internet **solo para la primera instalación**
- Ser usuario administrador (sudo)

---

## Paso 1 — Instalar (solo una vez, con internet)

Abre una terminal y escribe:

```bash
cd ~/adhoc-streaming-node
sudo bash scripts/install-fedora.sh
```

Esto descarga e instala todo lo necesario: programas, librerías y genera las 25 canciones de tu nodo. Tarda unos minutos. **Solo se hace una vez por laptop.**

Al terminar verás:
```
[+] Instalación completa en Fedora 43.
    Activar AD-HOC:     sudo scripts/adhoc-on.sh
    Restaurar internet: sudo scripts/adhoc-off.sh
```

---

## Paso 2 — Encender la red AD-HOC

```bash
sudo bash scripts/adhoc-on.sh
```

Este comando hace todo:
1. Desconecta la laptop del WiFi normal
2. Busca si ya hay una red `ADHOC-STREAM` encendida por otra laptop
3. Si la encuentra → se une a ella
4. Si no la encuentra → crea una red nueva y esta laptop se convierte en el "jefe" (Master)
5. Arranca el programa de música automáticamente

Al terminar verás algo así:
```
[ON] === AD-HOC ACTIVO ===
     Interfaz : wlp3s0
     SSID     : ADHOC-STREAM
     IP local : 192.168.99.30
     Cell ID  : 02:a3:f1:7c:2d:88
     Para apagar: sudo scripts/adhoc-off.sh

[ON] Daemon arrancado. Dashboard: http://192.168.99.30:8080
```

> **Mientras la red AD-HOC está activa, no tendrás internet normal.** Esto es normal.

---

## Paso 3 — Ver el panel de control

Abre un navegador web en cualquier laptop de la red y escribe la dirección que apareció, por ejemplo:

```
http://192.168.99.30:8080
```

Verás un panel verde oscuro con toda la información en tiempo real. Se actualiza cada 3 segundos solo.

---

## Paso 4 — Apagar y recuperar internet

```bash
sudo bash scripts/adhoc-off.sh
```

Este comando:
1. Para el programa de música
2. Desconecta la laptop de la red AD-HOC
3. Vuelve a conectar al WiFi normal automáticamente

---

## ¿Qué significa cada cosa en el panel?

| Lo que ves | Qué significa |
|---|---|
| **MASTER** (en dorado) | Esta laptop es la jefa — ella elige y transmite las canciones |
| **Cliente** (en gris) | Esta laptop recibe y reproduce lo que el Master transmite |
| **Tasa TX** | Qué tan rápido se están enviando los datos (ej: `54.0 Mbit/s`) |
| **Nodos activos** | Cuántas laptops están conectadas en este momento |
| **Señal** | Qué tan fuerte es la conexión con cada laptop (ej: `-46 dBm` — mientras más cercano a 0, mejor) |
| **Modulación** | El "idioma técnico" que usan las antenas para hablar entre sí |
| **Canciones locales** | Las 25 canciones que solo tiene esta laptop |
| **Canción en streaming** | La canción que está sonando ahora mismo |

---

## Cómo forzar una canción específica

Desde el panel web, en la sección "Transmisión":

1. Escribe el nombre del archivo en el cuadro de texto (ej: `song_05.mp3`)
2. Haz clic en **"Forzar canción"**

O haz clic directamente en cualquier botón de canción que aparece en la lista de canciones disponibles en la red. Los botones **verdes** son canciones locales de esta laptop, los **azules** son de otras laptops.

---

## Cómo probarlo

### Prueba 1 — Verificar que la red está activa

Después de correr `adhoc-on.sh`, en la terminal escribe:

```bash
iw dev wlp3s0 info
```

Busca la línea que diga `type IBSS` — eso confirma que estás en modo ad-hoc.

```
Interface wlp3s0
    type IBSS              ← esto debe aparecer
    ssid ADHOC-STREAM
    addr b0:68:e6:27:70:a7
```

---

### Prueba 2 — Ver que el programa está corriendo

```bash
sudo journalctl -u adhoc-node.service -n 30 --no-pager
```

Debes ver líneas como estas (sin errores rojos):
```
[INIT] Nodo 14139bb8 arrancando...
[NET] Creando IBSS propia...
[INIT] IS_MASTER=1
[INIT] Lanzando node-daemon.py...
Master elige aleatoriamente local: song_22.mp3
Iniciando servidor de stream local: song_22.mp3
```

---

### Prueba 3 — Verificar que el panel web funciona

```bash
curl -s http://192.168.99.30:8080/api/status | python3 -m json.tool | head -20
```

Debes ver un JSON con información del nodo:
```json
{
    "node_id": "14139bb8",
    "is_master": true,
    "current_streaming_song": "song_22.mp3",
    "local_songs": ["song_01.mp3", "song_02.mp3", ...],
    ...
}
```

---

### Prueba 4 — Con dos laptops (la prueba real)

Esta es la prueba más importante. Necesitas dos laptops con el sistema instalado.

**Laptop A** (primera en encenderse):
```bash
sudo bash scripts/adhoc-on.sh
```
Espera a ver `[ON] === AD-HOC ACTIVO ===`.

**Laptop B** (segunda):
```bash
sudo bash scripts/adhoc-on.sh
```

**Laptop B debería ver** algo como:
```
[ON] Encontrada: 02:a3:f1:7c:2d:88 @ 2412MHz (-58 dBm)
[ON] Uniéndose a red existente: 02:a3:f1:7c:2d:88
```

**Verificar que se ven entre sí:**
```bash
# En cualquiera de las dos laptops:
ping 192.168.99.30    # IP de la laptop A
ping 192.168.99.XX    # IP de la laptop B
```

**Verificar desde el panel web:** Abre `http://192.168.99.30:8080` — en la tarjeta "Peers activos" debe aparecer la otra laptop.

---

### Prueba 5 — Escuchar el stream de audio

En la laptop cliente (la que NO es Master), el audio debería empezar a sonar automáticamente por los altavoces. Si no suena:

```bash
# Ver si mpv está corriendo
ps aux | grep mpv

# Escuchar manualmente el stream
mpv --no-video udp://239.255.42.42:5004
```

---

### Prueba 6 — Forzar una canción vía terminal

```bash
# Reemplaza la IP con la del nodo Master
curl -X POST http://192.168.99.30:8080/api/force-song \
     -d "song=song_03.mp3"
```

Respuesta esperada:
```json
{"ok": true, "song": "song_03.mp3"}
```

---

### Prueba 7 — Simular separación de red

1. Apaga la red AD-HOC en la Laptop B: `sudo bash scripts/adhoc-off.sh`
2. Vuelve a encenderla: `sudo bash scripts/adhoc-on.sh`
3. La Laptop B debería detectar la red de la Laptop A y unirse sola

Si las pones físicamente lejos (fuera de rango), cada una crea su propia red. Cuando las acercas de nuevo, la que tiene menor score se une a la red de la que tiene mayor score en el siguiente ciclo de revisión (máximo 60 segundos).

---

## Solución rápida de problemas

**No veo el panel web:**
Verifica que el daemon esté corriendo:
```bash
sudo systemctl status adhoc-node.service
```
Si dice `failed`, revisa el log:
```bash
sudo journalctl -u adhoc-node.service -n 50 --no-pager
```

**No hay audio en los clientes:**
```bash
# ¿Está mpv instalado?
which mpv

# ¿Hay stream activo en la red?
sudo timeout 5 tcpdump -i wlp3s0 udp port 5004 -c 5
```

**Quiero volver a empezar desde cero:**
```bash
sudo bash scripts/reset-node.sh
```
Te pregunta confirmación y borra todo. Después puedes reinstalar con `install-fedora.sh`.

**Perdí el internet y no sé cómo recuperarlo:**
```bash
sudo bash scripts/adhoc-off.sh
```
Este comando siempre restaura el internet, aunque el daemon esté caído.
