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

## Universo Ramos Arizpe

En la página **Universo Ramos Arizpe**, usa **Actualizar desde Excel** y selecciona `Copia de UNIVERSO RAMOS.XLSX`. La carga usa la hoja `Sheet1 (2)` y relaciona cada número de parte con su cliente y diámetro. El Universo muestra las piezas del archivo; las demás piezas siguen disponibles para órdenes e inventario. Las descripciones no forman parte de este catálogo.

Para dar de alta piezas sin reemplazar el Universo, descarga la plantilla de **Agregar piezas desde Excel**. Llena la hoja `Sheet1` con número de parte y cliente; diámetro y peso son opcionales. La carga rechaza números repetidos, incluso si solo cambia el uso de mayúsculas, y no guarda ninguna fila si el archivo tiene errores. La tabla permite filtrar por fecha de incorporación al Universo y se ordena desde la primera subida hasta la última; los registros sin fecha quedan al final.

### Editar piezas del Universo

En **Universo Ramos Arizpe**, cada pieza muestra **Editar** para las cuentas con
los permisos **consultar Universo Ramos Arizpe** y **editar Universo Ramos Arizpe**.
El formulario permite cambiar número de parte, cliente, diámetro y peso unitario;
valida duplicados y conserva la pieza vinculada a sus órdenes e inventario.
La fecha de incorporación y la pertenencia al Universo no cambian al editar.
Los cambios quedan registrados en auditoría y al volver se conservan los filtros.

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

## Órdenes de muestra

La casilla **Muestra** se encuentra en la carga individual, en cada fila de la vista previa de Excel y al editar una orden. Una orden nueva marcada como muestra usa 5 piezas requeridas, tanto en la interfaz como en la validación del servidor. Desmarcar una fila de la vista previa recupera la cantidad original del Excel. Editar la clasificación de una orden existente conserva su cantidad y saldo; no se aplica retroactivamente la regla de 5.

Las órdenes usan el mismo número de parte normal y muestran **(MUESTRAS)** en programación, producción, reportes y exportaciones. Se pueden filtrar muestras o normales en **Programas y órdenes**.

La migración `0017` vincula las piezas históricas con sufijo `(MUESTRAS)` a una pieza normal solo si el código coincide de forma inequívoca y el cliente es el mismo. Las órdenes antiguas mantienen sus identificadores, piezas originales, cantidades, saldos y pesos. Las cargas nuevas resuelven esos alias a la pieza normal. Los números sin coincidencia y las coincidencias con cliente distinto permanecen intactos. Los alias se conservan para sostener el historial y dejan de ofrecerse como piezas independientes en el selector de edición de otras órdenes.

El catálogo y sus contadores excluyen estos alias históricos, también al elegir **Ver todos los números** o buscar. Los números sin coincidencia y los de cliente distinto siguen visibles. La consulta de inventario y los registros de producción conservan sus vínculos históricos.

La migración `0018` convierte los códigos nuevos con sufijo `(MUESTRAS)` a números normales cuando no existe otro número equivalente. Usa el mismo identificador de pieza, conserva el nombre original en `legacy_number` y auditoría, y mueve al campo diámetro la medida explícita al final del nombre. Las órdenes anteriores se marcan como muestra conservando sus cantidades y relaciones; las nuevas órdenes normales pueden usar el código limpio. Los archivos antiguos siguen resolviéndose por el nombre anterior. Los diámetros desconocidos permanecen vacíos y las coincidencias ambiguas no se convierten.

Por confirmación del usuario, `0019` oculta las cinco versiones de muestra de RHEEM CIP-3501 cuyos originales correctos pertenecen a DAIKIN. Sus clientes históricos y vínculos de producción permanecen intactos; la relación de alias señala la pieza original para futuras cargas y para excluir los duplicados del catálogo.

## Catálogo conectado a Universo Ramos

Configura `UR_BASE_URL` (HTTPS) y `UR_API_KEY` en el `.env` privado del servidor; la clave nunca debe incluirse en Git. Construye la imagen con `docker compose build web`, aplica las migraciones y ejecuta `docker compose run --rm --no-deps web python manage.py sync_universe_ramos`. Después inicia `docker compose up -d web universe-sync`. El sincronizador actualiza cada cinco minutos; la pantalla Universo permite **Sincronizar ahora** a quienes ya tienen permiso de edición o importación.

La primera sincronización completa habilita el catálogo central y bloquea altas, ediciones e importaciones locales de piezas. Se reutilizan los `Part.id` existentes por número normalizado, y desde entonces se vinculan por UUID central. Se conservan las equivalencias de muestras y la corrección `48TM004286` → `48TM004286B`; las nuevas capturas resuelven estos alias al registro principal. Los números desconocidos o no disponibles en la API se rechazan al crear órdenes. Los datos del cliente del Excel o la captura no sustituyen al cliente del catálogo central.

Cliente, diámetro y peso mostrado en el catálogo provienen de la API. El campo central de peso no declara unidad: configura `UR_WEIGHT_UNIT=kg` o `g` solo después de confirmarla. Si está vacío, se conserva el peso operativo local en kilogramos y el peso central se consulta sin convertir; así no se asumen unidades ni se alteran los cálculos existentes. `local_catalog_snapshot` conserva los datos originales de cada pieza vinculada; `central_payload` conserva las demás columnas centrales. Un peso nulo permanece vacío. Las órdenes, saldos, inventarios, movimientos, cierres y sus pesos históricos no se recalculan ni se reasignan. Las piezas inactivas, retiradas o no autorizadas quedan fuera del catálogo y de las nuevas órdenes, conservando sus registros históricos. Una pieza pendiente de aprobación en Universo Ramos no convierte automáticamente sus órdenes en muestras: la casilla de muestra de la orden sigue controlando la cantidad nueva de cinco piezas.

Cada sincronización reconstruye la selección permitida, reproduce los cambios desde el cursor de bootstrap y confirma toda la actualización en una transacción. Un cambio de política reinicia la descarga, y un error conserva la caché anterior. No se requieren conexiones a la API para consultar ni cerrar producción. No se almacenan claves en la base de datos ni se muestran en pantalla o registros.

## Módulos operativos

- Inventario por número de parte, programa y proceso.
- Órdenes abiertas.
- Asignación a máquinas disponibles.
- Cierres totales y parciales con cálculo correcto de peso.
- Historial y exportación CSV.
- Usuarios, catálogos y auditoría desde Django Admin.

## Corrección de cierres desde Reportes

En `/admin/`, abre **Usuarios**, selecciona a la persona y activa **reportes** y
**eliminar cierres desde reportes** en sus accesos a módulos. El nuevo permiso
está desactivado por defecto; los superusuarios tienen acceso.

En Reportes aparece **Eliminar cierre** para las personas autorizadas. La pantalla
de confirmación exige un motivo y muestra las piezas que se devolverán. Si el
proceso sigue activo, las piezas vuelven a su saldo; si ya terminó, vuelven a la
orden disponible sin reactivar la máquina. Esto permite recuperar, por ejemplo,
un saldo de 0.9 piezas al eliminar un cierre incorrecto de 0.1.

El cierre se elimina de reportes y gráficas; la auditoría conserva su folio,
cantidad, peso, fecha, operador original, usuario que eliminó y motivo.
La devolución se bloquea si excede el saldo permitido o intenta reabrir una orden
por encima de la capacidad global. La eliminación directa en Django Admin está
deshabilitada para evitar que se omita la devolución de piezas.

Para habilitar el nuevo permiso en una instalación existente, ejecuta
`python manage.py migrate` (Docker también aplica migraciones al arrancar).

# Proyecto-Heliang
