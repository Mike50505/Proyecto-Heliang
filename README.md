# MESA Producción Web

Migración web de la aplicación de inventario y producción originalmente implementada en Excel/VBA.

## Arranque local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Abrir `http://127.0.0.1:8000/`.

## Importar el libro histórico

Primero se recomienda una simulación:

```bash
.venv/bin/python manage.py import_excel \
  "MATERIAL EN PROCESO_Rev97. - INTEGRANDO - RAMOS A.xlsm" \
  --orders Sheet1.xlsx --dry-run
```

Para guardar los datos, ejecutar el mismo comando sin `--dry-run`. La operación completa es atómica: si ocurre un error, no deja una importación parcial.

Las cuentas encontradas en `ADMINISTRADORES` se crean con contraseña inutilizable; un administrador debe asignarles una contraseña segura desde `/admin/`.

## Docker y PostgreSQL

```bash
docker compose up --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py import_excel "/ruta/dentro/del/contenedor/libro.xlsm"
```

En un servidor se deben configurar `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY` y `DJANGO_ALLOWED_HOSTS` mediante variables de entorno.

## Módulos disponibles

- Inventario por número de parte, programa y proceso.
- Órdenes abiertas.
- Asignación a máquinas disponibles.
- Cierres totales y parciales con cálculo correcto de peso.
- Historial y exportación CSV.
- Usuarios, catálogos y auditoría desde Django Admin.

# Proyecto-Heliang
