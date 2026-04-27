# ansible/

Despliegue automatizado en múltiples nodos.

## Archivos

- `inventory.ini` — Lista de hosts/nodos.
- `playbook.yml` — Instala dependencias, copia repo, registra servicio en **Ubuntu/Debian**.
- `playbook-fedora.yml` — Versión para **Fedora 43+** con dnf, SELinux, firewalld y NetworkManager.

## Uso

### Ubuntu / Debian
```bash
ansible-playbook -i inventory.ini playbook.yml
```

### Fedora 43
```bash
ansible-playbook -i inventory.ini playbook-fedora.yml
```
