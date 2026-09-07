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

## Debian, red local y Tailscale

En la carpeta del proyecto, crea `.env` a partir de `.env.example` si aún no
existe. No sobrescribas un `.env` existente. Docker Compose lee ese archivo y
pasa al contenedor web las variables declaradas en `compose.yaml`.
`settings.py` lee el entorno; al ejecutar Django sin Compose debes exportar
las variables tú mismo.

```dotenv
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,100.90.206.74,IP_LAN_REAL_DEL_SERVIDOR
DJANGO_SECRET_KEY=REEMPLAZAR_POR_LA_CLAVE_DEL_SERVIDOR
POSTGRES_PASSWORD=REEMPLAZAR_POR_LA_CONTRASENA_DE_POSTGRES
DJANGO_CSRF_TRUSTED_ORIGINS=
```

Reemplaza los marcadores antes de arrancar. `ALLOWED_HOSTS` contiene IP o nombres
sin protocolo ni puerto; los espacios y entradas vacías se ignoran y `*` se
rechaza. `DJANGO_DEBUG` acepta `0/1`, `false/true`, `no/yes` y `off/on`.
Sin variables se conservan los valores de desarrollo local; en Debian usa
`DJANGO_DEBUG=0` y una clave privada. Con DEBUG desactivado, Django rechaza las
claves de ejemplo incluidas para desarrollo.

Si ya existe una base, usa su contraseña **actual**: cambiar `POSTGRES_PASSWORD`
en `.env` no cambia la contraseña de una base ya inicializada y puede impedir
la conexión. Conserva también la `DJANGO_SECRET_KEY` del despliegue existente.
Para una instalación nueva, genera ambos secretos de forma independiente en
el servidor, por ejemplo ejecutando `openssl rand -hex 32` dos veces. No uses
los marcadores de este documento como secretos. Protege el archivo con
`chmod 600 .env`. `.env` y sus variantes están excluidos de Git y del contexto
de construcción de Docker; solo `.env.example` se versiona.

```bash
docker compose config --quiet
docker compose up -d --build
```

Después abre `http://100.90.206.74:8000/` desde un equipo de la misma tailnet,
o `http://IP_LAN_REAL_DEL_SERVIDOR:8000/` desde la LAN. El servidor Debian debe
tener Tailscale conectado con esa IP y sus reglas de acceso y firewall deben
permitir TCP 8000 desde esos equipos. No necesitas abrir puertos en el router
para Tailscale. `ALLOWED_HOSTS` valida el destino HTTP; no sustituye al firewall.

Solo `web` publica el puerto 8000. `db` no publica el puerto 5432 y está
conectado únicamente a la red Docker `database`, marcada como `internal`.
El servicio web accede a PostgreSQL por `db:5432`.

Se conservan el volumen `postgres_data`, la base `mesa`, el usuario `mesa` y
la ruta de datos. Mantén el mismo nombre de proyecto Compose y la misma
ubicación del despliegue para reutilizar su volumen; no ejecutes
`docker compose down -v`. Copiar el repositorio a otro servidor no transfiere
la base de datos: esa transferencia requiere un respaldo y una restauración
por separado. El arranque existente sigue ejecutando las migraciones pendientes
y `collectstatic`; esta configuración no agrega migraciones ni cambia modelos.

### CSRF y HTTPS a futuro

Para el acceso directo actual mediante `http://100.90.206.74:8000/`, deja
`DJANGO_CSRF_TRUSTED_ORIGINS` vacío. Las peticiones del mismo origen ya son
válidas. Si necesitas autorizar un origen adicional, define su URL exacta,
incluyendo `https://` y el puerto si no es el estándar, por ejemplo
`DJANGO_CSRF_TRUSTED_ORIGINS=https://produccion.example.com`. Añade también
`produccion.example.com` a `DJANGO_ALLOWED_HOSTS` si accederás por ese nombre.

HTTPS por sí solo no exige agregar orígenes confiables si Django reconoce
correctamente el esquema de la petición. Al incorporar un proxy HTTPS,
Tailscale Serve o Cloudflare, revisa la terminación TLS y las cabeceras del
proxy. Solo habilita `SECURE_PROXY_SSL_HEADER` cuando el proxy sea de confianza
y reemplace las cabeceras enviadas por el cliente. Entonces revisa también
cookies seguras y redirecciones a HTTPS. Aquí no se activan esas opciones para
no interrumpir el acceso HTTP actual, ni se desactiva la protección CSRF.

Referencias: [variables de Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/),
[redes internas](https://docs.docker.com/reference/compose-file/networks/#internal),
[ALLOWED_HOSTS y CSRF](https://docs.djangoproject.com/en/5.2/ref/settings/).

## Módulos disponibles

- Inventario por número de parte, programa y proceso.
- Órdenes abiertas.
- Asignación a máquinas disponibles.
- Cierres totales y parciales con cálculo correcto de peso.
- Historial y exportación CSV.
- Usuarios, catálogos y auditoría desde Django Admin.

# Proyecto-Heliang
