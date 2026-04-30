# Clonar USB desde Windows

## Lo que necesitas

- [Win32 Disk Imager](https://sourceforge.net/projects/win32diskimager/)
- [7-Zip](https://www.7-zip.org/) (para comprimir antes de subir a Drive)
- [balenaEtcher](https://etcher.balena.io/) (para escribir la imagen en nuevas USB)
- Espacio libre en el SSD para guardar la imagen temporalmente

---

## Paso 1 — Crear la imagen de la USB

1. Conecta la USB con tu Linux al PC
2. Abre **Win32 Disk Imager** como administrador
3. En **Image File**, escribe la ruta donde quieres guardar la imagen, por ejemplo:
   ```
   C:\Backups\usb_linux.img
   ```
4. En **Device**, selecciona la letra de tu USB (ej: `[F:]`)
5. Haz clic en **Read**
6. Espera a que termine — el tiempo depende del tamaño de la USB

> Al terminar tendrás un archivo `.img` del tamaño exacto de tu USB.

---

## Paso 2 — Comprimir la imagen (opcional pero recomendado)

Para ahorrar espacio y subir más rápido a Google Drive:

1. Clic derecho sobre `usb_linux.img`
2. **7-Zip → Añadir al archivo...**
3. Formato: `7z` o `zip`
4. Haz clic en **Aceptar**

---

## Paso 3 — Subir a Google Drive

1. Abre [drive.google.com](https://drive.google.com) o el cliente de escritorio de Google Drive
2. Crea una carpeta llamada `Backups USB` (o como prefieras)
3. Sube el archivo `.img` o el comprimido

---

## Paso 4 — Clonar la imagen en nuevas USB

Para cada USB que quieras clonar:

1. Conecta la USB destino
2. Abre **balenaEtcher**
3. **Flash from file** → selecciona `usb_linux.img`
4. **Select target** → selecciona la USB destino
5. Haz clic en **Flash!**
6. Espera a que termine y se verifique automáticamente

Repite desde el punto 1 para cada USB adicional.

---

## Paso 5 — Restaurar desde Google Drive (cuando lo necesites)

1. Descarga el archivo desde Google Drive
2. Si está comprimido, extráelo con 7-Zip
3. Abre **balenaEtcher** y repite el Paso 4

---

## Resumen

| Paso | Herramienta | Acción |
|------|-------------|--------|
| Crear imagen | Win32 Disk Imager | Read → `usb_linux.img` |
| Comprimir | 7-Zip | `.img` → `.7z` o `.zip` |
| Subir | Google Drive | Subir el archivo |
| Clonar USB | balenaEtcher | Flash `usb_linux.img` → USB |
