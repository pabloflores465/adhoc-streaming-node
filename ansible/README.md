# ansible/

Despliegue automatizado en múltiples nodos.

## Archivos

- `inventory.ini` — Lista de hosts/nodos.
- `playbook.yml` — Instala dependencias, copia repo, registra servicio.

## Uso

```bash
ansible-playbook -i inventory.ini playbook.yml
```
