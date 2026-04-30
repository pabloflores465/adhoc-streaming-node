# Guía: Clonar USB exactamente y subir a Google Drive

## Requisitos previos

- Linux (cualquier distro)
- Paquetes: `dd`, `pv` (opcional, para ver progreso), `gzip` (compresión), `rclone` (para Google Drive)
- Espacio en disco suficiente para guardar la imagen temporal

---

## Paso 1 — Identificar tu USB origen

Conecta la USB y ejecuta:

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,LABEL
```

o:

```bash
sudo fdisk -l
```

Identifica el dispositivo, por ejemplo: `/dev/sdb` (no una partición como `/dev/sdb1`).

> **IMPORTANTE:** Confirma bien el dispositivo antes de continuar. Un error aquí puede sobreescribir datos.

---

## Paso 2 — Crear imagen exacta de la USB

### Opción A: imagen sin comprimir (más rápido de escribir después)

```bash
sudo dd if=/dev/sdX of=~/usb_backup.img bs=4M status=progress
```

### Opción B: imagen comprimida con gzip (menos espacio, ideal para subir a Drive)

```bash
sudo dd if=/dev/sdX bs=4M status=progress | gzip -c > ~/usb_backup.img.gz
```

### Opción C: con `pv` para barra de progreso detallada

```bash
sudo dd if=/dev/sdX bs=4M | pv | gzip -c > ~/usb_backup.img.gz
```

Reemplaza `/dev/sdX` con tu dispositivo real (ej: `/dev/sdb`).

---

## Paso 3 — Verificar la imagen (opcional pero recomendado)

```bash
# Ver info de la imagen
file ~/usb_backup.img

# Verificar tamaño
ls -lh ~/usb_backup.img
```

---

## Paso 4 — Escribir la imagen en nuevas USB

Para cada USB destino:

1. Conecta la USB destino y confirma su dispositivo con `lsblk`
2. Escribe la imagen:

### Si la imagen es `.img` (sin comprimir):

```bash
sudo dd if=~/usb_backup.img of=/dev/sdY bs=4M status=progress
sync
```

### Si la imagen es `.img.gz` (comprimida):

```bash
gunzip -c ~/usb_backup.img.gz | sudo dd of=/dev/sdY bs=4M status=progress
sync
```

Reemplaza `/dev/sdY` con el dispositivo de la USB destino.

> Repite este paso para cada USB adicional que quieras clonar.

---

## Paso 5 — Subir la imagen a Google Drive con rclone

### 5.1 — Instalar rclone (si no lo tienes)

```bash
sudo -v && curl https://rclone.org/install.sh | sudo bash
```

### 5.2 — Configurar Google Drive

```bash
rclone config
```

Sigue los pasos interactivos:
- Elige `n` (new remote)
- Nombre: `gdrive` (o el que prefieras)
- Tipo: `drive` (Google Drive)
- Deja client_id y client_secret vacíos (usa los de rclone por defecto)
- Scope: `1` (acceso completo)
- Sigue el enlace de autenticación que aparece en el navegador

### 5.3 — Subir la imagen

```bash
# Subir imagen comprimida (recomendado)
rclone copy ~/usb_backup.img.gz gdrive:Backups/USB --progress

# O imagen sin comprimir
rclone copy ~/usb_backup.img gdrive:Backups/USB --progress
```

Esto creará la carpeta `Backups/USB` en tu Google Drive.

---

## Paso 6 — Restaurar desde Google Drive (cuando lo necesites)

```bash
# Descargar la imagen
rclone copy gdrive:Backups/USB/usb_backup.img.gz ~/usb_backup.img.gz --progress

# Escribir en nueva USB
gunzip -c ~/usb_backup.img.gz | sudo dd of=/dev/sdY bs=4M status=progress
sync
```

---

## Resumen de comandos clave

| Tarea | Comando |
|-------|---------|
| Ver discos | `lsblk -o NAME,SIZE,TYPE,MOUNTPOINT` |
| Crear imagen | `sudo dd if=/dev/sdX bs=4M \| gzip -c > usb_backup.img.gz` |
| Clonar a USB | `gunzip -c usb_backup.img.gz \| sudo dd of=/dev/sdY bs=4M status=progress` |
| Subir a Drive | `rclone copy usb_backup.img.gz gdrive:Backups/USB --progress` |
| Bajar de Drive | `rclone copy gdrive:Backups/USB/usb_backup.img.gz . --progress` |

---

## Notas importantes

- **No desconectes la USB** durante la creación de la imagen.
- Ejecuta `sync` después de escribir en cada USB para asegurarte de que todos los datos fueron volcados.
- Si la imagen comprimida supera los 5 GB, Google Drive puede tardar bastante en subir; considera dividirla con `split`.
- Para dividir archivos grandes:
  ```bash
  split -b 4G usb_backup.img.gz usb_parte_
  # Recombinar:
  cat usb_parte_* > usb_backup.img.gz
  ```
