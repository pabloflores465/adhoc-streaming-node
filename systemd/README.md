# systemd/

Unidades de servicio para autoarranque del nodo como proceso.

## Servicios

- `adhoc-node.service` — Servicio principal. Lanza el daemon de nodo al boot.
- `adhoc-network.service` — Configura red IBSS antes de levantar el daemon.

## Instalación

```bash
sudo cp *.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable adhoc-node.service
```

## Estado

```bash
sudo systemctl status adhoc-node.service
sudo journalctl -u adhoc-node.service -f
```
