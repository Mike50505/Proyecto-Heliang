# Integración de Heilians con EDH: inspección del repositorio

**Estado:** análisis y propuesta; no hay integración implementada. Inspección de Heilians en `main`, commit `4337d081747fc3864f7a66db5c2cf87009177a88`, repositorio [Mike50505/Proyecto-Heliang](https://github.com/Mike50505/Proyecto-Heliang). Fecha de revisión: 2026-10-05. Los datos de EDH indicados abajo proceden del contexto entregado con esta solicitud; no se auditó el código de EDH. El usuario confirmó las correspondencias ITEM PADRE, SEMANA y CANTIDAD el 2026-10-05.

## 1. Arquitectura y conectividad comprobadas

Heilians es una aplicación Django 5.2 con vistas y plantillas HTML, JavaScript en las plantillas, autenticación de sesión de Django y PostgreSQL en Docker Compose. `requirements.txt` no incluye Django REST Framework. En desarrollo puede usar SQLite si `POSTGRES_DB` no está definido. El contenedor web ejecuta Gunicorn en el puerto interno 8000 y Compose publica **80:8000**; la base está en una red Docker interna. Fuentes: [requirements.txt](requirements.txt), [config/settings.py](config/settings.py#L38), [compose.yaml](compose.yaml#L1), [Dockerfile](Dockerfile), [entrypoint.sh](entrypoint.sh), [README.md](README.md).

En el entorno inspeccionado, `macros-web-1` (Heilians) publica el puerto 80 y `proyectoedh-web-1` (EDH) el 8000. No comparten red Docker: Heilians pertenece a `macros_default` y `macros_database`; EDH pertenece a `proyectoedh_default`. Una solicitud HTTP de solo lectura desde Heilians a `host.docker.internal:8000/imprimir-lote/` recibió **400**. Eso demuestra que se alcanzó un servidor HTTP en ese puerto, pero no que la URL de EDH esté correctamente configurada o que el flujo autenticado funcione. La causa del 400 requiere verificación en EDH; una política de `Host` es una posibilidad, no un hecho demostrado. Para despliegue se debe definir DNS/URL y ruta de red entre servidores, preferentemente HTTPS; `host.docker.internal` no es una dirección de producción portable. No se confirmó desde el repositorio la IP, VPN o URL pública definitiva de ninguno de los dos servicios. Fuente de configuración: [compose.yaml](compose.yaml#L19), [config/settings.py](config/settings.py#L21).

## 2. Correspondencia de campos

| Dato requerido por EDH | Campo real en Heilians | Tipo y observación |
| --- | --- | --- |
| Identificador estable de orden | `ProductionOrder.folio` | `CharField(40, unique=True)`; adecuado como `external_order_id`. El `pk` sirve para la selección interna. |
| Identificador de trabajo activo | `WorkInProcess.folio` | `CharField(40, unique=True)`; conviene enviarlo también para diagnosticar filas y evitar mezclar dos trabajos de una orden. |
| ITEM PADRE | `ProductionOrder.part.number` | `Part.number` es `CharField(80, unique=True)`. Heilians no modela relación padre/componente; el usuario confirmó que este número corresponde a ITEM PADRE para la integración. |
| SEMANA | `ProductionOrder.program` | `CharField(80)`, usado como “Semana / orden de producción” en la pantalla y como `week` en el tablero de avance. Puede contener `31A` o ceros iniciales porque es texto; no hay campo separado ni validación de formato de semana. El usuario confirmó que este campo siempre representa SEMANA. |
| CANTIDAD para EDH | `ProductionOrder.quantity` | `DecimalField(14,3)`, positiva. El usuario confirmó que se envía este campo, sin sustituirlo por saldos ni sumas de trabajos. |
| Saldo de orden sin asignar | `ProductionOrder.remaining_quantity` | `DecimalField(14,3)`; disminuye al iniciar trabajo. **No** equivale por sí solo a cantidad en máquina. |
| Cantidad del trabajo en proceso | `WorkInProcess.remaining_quantity` | `DecimalField(14,3)`; saldo del trabajo activo. `initial_quantity` guarda lo asignado al iniciarlo. |
| Cantidad terminada | Suma de `ProductionClose.quantity` por trabajos de la orden | `DecimalField(14,3)`; el tablero de avance ya suma cierres. |
| Cliente | `Part.client.name` | Relación opcional con `Client`; también hay `Client.code` único y `external_id` opcional. |
| Planta | Sin campo identificado | No inferirla de cliente, máquina ni archivo de origen. |
| LINEA | `ProductionOrder.line` | `CharField(80, blank=True)`; es línea de la orden/cliente. Confirmar si corresponde a la LINEA común que imprime EDH cuando se seleccionan varias órdenes. |
| PLANNER, RESPONSABLE | Sin campos de orden identificados | Pueden quedar vacíos u obtenerse por captura opcional del usuario, sin deducirlos de `loaded_by` o `started_by`. |
| Estado | `ProductionOrder.status` y `WorkInProcess.status` | Son estados distintos; usar el del trabajo para identificar producción en curso. |

Fuentes: [operations/models.py](operations/models.py#L16), [operations/models.py](operations/models.py#L82), [operations/models.py](operations/models.py#L109), [operations/models.py](operations/models.py#L136), [operations/forms.py](operations/forms.py#L74), [operations/views.py](operations/views.py#L1130), [templates/operations/order_list.html](templates/operations/order_list.html#L35).

La carga masiva toma “Orden de Produccion” del Excel y la guarda como `program`; si la celda se creó como número en Excel, los ceros iniciales podrían haberse perdido antes de llegar a Django. Para futuras cargas y la integración, tratar SEMANA como texto de extremo a extremo y no convertirla a entero. Fuentes: [operations/views.py](operations/views.py#L315), [operations/views.py](operations/views.py#L463).

## 3. Estados y filtro exacto de “en proceso”

`ProductionOrder.Status`: `OPEN` (Abierta), `ALLOCATED` (Asignada), `COMPLETE` (Completada), `CANCELLED` (Cancelada). `WorkInProcess.Status`: `ACTIVE` (Procesando), `CLOSED` (Cerrada). Fuentes: [operations/models.py](operations/models.py#L82), [operations/models.py](operations/models.py#L109).

`start_production` acepta una orden `OPEN`, crea un `WorkInProcess.ACTIVE` y descuenta la cantidad asignada del saldo de la orden. Solo cambia la orden a `ALLOCATED` cuando su saldo sin asignar llega a cero. **Una orden `OPEN` puede tener trabajo activo** si se asignó parcialmente. `close_production` cierra el trabajo, registra la cantidad terminada y devuelve el sobrante no producido al saldo abierto; la orden se completa cuando ya no queda saldo ni trabajo activo. Fuentes: [operations/services.py](operations/services.py#L320), [operations/services.py](operations/services.py#L345).

Filtro recomendado al enviar a EDH, validado nuevamente en el servidor al pulsar el botón:

`WorkInProcess.objects.filter(status=ACTIVE, remaining_quantity__gt=0, order__status__in=[OPEN, ALLOCATED]).select_related("order__part__client")`

Excluir trabajos cerrados, órdenes completadas/canceladas y piezas sin `part.number` o programa/semana vacío. Agrupar por `order_id` y enviar **una fila por orden**; una orden puede tener varios trabajos activos y su `quantity` no debe duplicarse. El `status=ALLOCATED` aislado es insuficiente. La vista Heliang ya muestra trabajos activos con este modelo; `work_list` presenta los últimos 500 trabajos de cualquier estado. Fuentes: [operations/views.py](operations/views.py#L908), [operations/views.py](operations/views.py#L1012), [templates/operations/heliang.html](templates/operations/heliang.html), [templates/operations/work_list.html](templates/operations/work_list.html).

### Qué cantidad imprimir

La pantalla **Programas y órdenes** muestra `order.quantity` y `order.remaining_quantity`; la columna de Heliang **Números en proceso** muestra `work.initial_quantity` y `work.remaining_quantity`. El tablero de avance muestra programada y terminada, esta última calculada con cierres. Fuentes: [templates/operations/order_list.html](templates/operations/order_list.html#L35), [templates/operations/heliang.html](templates/operations/heliang.html), [operations/views.py](operations/views.py#L1130).

**Decisión confirmada por el usuario:** enviar `ProductionOrder.quantity` como CANTIDAD, serializada como cadena decimal (ejemplo `"10.500"`). El estado y saldo de `WorkInProcess` solo determinan qué órdenes están en proceso y pueden seleccionarse; no modifican la cantidad enviada. El servidor debe volver a leer `order.quantity` al confirmar, exigir `> 0` y avisar si cambió desde que se mostró la pantalla.

## 4. API y autenticación existentes

Heilians expone vistas Django en [operations/urls.py](operations/urls.py) bajo [config/urls.py](config/urls.py), sin prefijo `/api/` ni API JSON de órdenes. Los endpoints relevantes son:

| Ruta actual | Método/formato | Acceso y alcance |
| --- | --- | --- |
| `/ordenes/` | GET HTML, filtros `q`, `status`, `start`, `end`, `priority=1`; tabla limitada a 500 | Sesión y permiso `program_loading`; incluye todos los clientes, sin partición por planta. |
| `/produccion/` | GET HTML, últimos 500 trabajos | Sesión y permiso `heliang`; no filtra solo activos. |
| `/heliang/` | GET/POST HTML; formularios de iniciar/cerrar | Sesión, CSRF en POST y permiso `heliang`; contiene lista de trabajos activos. |
| `/tablero-avance/datos/` | GET JSON `{progress_data: [...], updated_at: ...}`; hasta 5,000 órdenes no canceladas | Sesión y permiso `line_dashboard`. Cada fila tiene `folio`, `week`, `client`, `part`, `programmed`, `completed` como números de punto flotante. No incluye estado, saldo activo, ID de trabajo ni paginación. **No sirve como contrato de integración de rutas**. |
| `/tablero-linea/datos/` | GET JSON con HTML renderizado y `updated_at` | Sesión y permiso `line_dashboard`; no es API de órdenes. |
| `/ordenes/<pk>/prioridad/` | POST de formulario; respuesta JSON con prioridad o error (400/405/409) | Sesión, CSRF y `program_loading`; no exporta datos de órdenes. |

Fuentes: [operations/urls.py](operations/urls.py), [operations/views.py](operations/views.py#L53), [operations/views.py](operations/views.py#L209), [operations/views.py](operations/views.py#L1114), [operations/views.py](operations/views.py#L1130). No existe paginación API ni contrato JSON para selección; las vistas protegidas redirigen al inicio de sesión o al tablero si falta permiso, por lo que tampoco ofrecen errores JSON uniformes.

Ejemplo **ilustrativo del formato existente** de `GET /tablero-avance/datos/` (valores ficticios, no respuesta capturada): `{"progress_data":[{"folio":"O-EJEMPLO-001","week":"31A","client":"Cliente A","part":"ITEM-001","programmed":10.5,"completed":2.0}],"updated_at":"2026-10-05T09:00:00-06:00"}`. No hay en esa respuesta una cantidad activa ni un estado de trabajo; tampoco hay endpoint para pedir una orden por `folio`. Fuente: [operations/views.py](operations/views.py#L1130).

La autenticación actual es la sesión de Django; `login_required` y `module_required` aplican permisos por módulo, con superusuarios autorizados. `CsrfViewMiddleware` protege POST del navegador. No se encontró autorización por fila, cliente ni planta. Fuentes: [operations/access.py](operations/access.py#L13), [operations/models.py](operations/models.py#L209), [config/settings.py](config/settings.py#L38). No conviene usar la cookie de Heilians como credencial de EDH.

## 5. Pantalla y flujo recomendados — **a implementar**

Colocar **Imprimir rutas** en la sección **Números en proceso** de `/heliang/`, donde ya se muestran solo trabajos activos, o en `/produccion/` tras filtrar allí solo los activos. Añadir casillas de selección múltiple y un botón separado de las acciones de cerrar producción. La tabla de `/ordenes/` ya tiene casillas, pero pertenecen al formulario **Eliminar seleccionadas** y mezclan órdenes abiertas/completadas; no reutilizar esa acción sin un flujo separado. Fuentes: [templates/operations/heliang.html](templates/operations/heliang.html), [templates/operations/work_list.html](templates/operations/work_list.html), [templates/operations/order_list.html](templates/operations/order_list.html#L20).

1. El navegador envía a un nuevo POST de Heilians los `pk` de trabajos u órdenes seleccionados, con sesión Heilians y CSRF. El backend comprueba permiso `heliang`, máximo 200 órdenes, estado `ACTIVE`, `order.quantity > 0`, cliente/semana/item y vuelve a leer los valores. Si una orden tiene varios trabajos activos, envía una sola fila con `order.quantity` una sola vez.
2. Heilians envía desde el servidor una solicitud HTTPS a un **nuevo endpoint de integración de EDH**. Autenticación entre servicios mediante una clave de firma con identificador de clave (o mTLS), firma del cuerpo, marca de tiempo y protección contra repetición; no enviar credenciales en la URL ni usar cookies de usuarios entre aplicaciones. Configuración prevista en Heilians: `EDH_BASE_URL`, `EDH_INTEGRATION_KEY_ID`, `EDH_INTEGRATION_SIGNING_KEY`, `EDH_REQUEST_TIMEOUT_SECONDS`, `EDH_REVIEW_BASE_URL`; en EDH, nombres equivalentes para claves autorizadas y origen permitido. Solo los **nombres** se documentan aquí.
3. EDH valida el contrato y conserva la selección en almacenamiento **temporal con vencimiento** (por ejemplo, caché con TTL y referencia opaca de un solo uso), sin crear programación ni documentos emitidos. Devuelve una URL de revisión. El navegador navega en la ventana principal al origen de EDH; allí el usuario inicia sesión en EDH si es necesario. La sesión de EDH es propia de ese origen y se mantiene durante la revisión. La referencia temporal no sustituye la autorización del usuario en EDH.
4. EDH resuelve rutas. Si un ITEM PADRE tiene varias rutas vigentes, presenta las opciones con cliente y datos de ruta para elección explícita; no toma la primera ni obliga a Heilians a conocer el archivo de origen. Excluye rutas archivadas y conserva advertencias/controles existentes para rutas por revisar. Tras confirmar, llama a `build_pdf(..., template_key=..., label_mode=...)` y devuelve PDF para vista previa/descarga/impresión del navegador, sin emisión aprobada implícita.

El contexto recibido indica que EDH hoy solo tiene `/imprimir-lote/` como formulario de sesión+CSRF y **no** tiene API JSON externa. Por eso el paso 2 exige implementación en EDH. El límite de 200 filas, `parent_code`, `quantity > 0`, `week` no vacía y `route_id` opcional proceden del contexto EDH aportado, no de una auditoría de su código.

### Contrato JSON propuesto; no existe todavía

Solicitud de ejemplo con órdenes **ficticias**. `external_work_ids` identifica los trabajos activos que hacen elegible a cada orden; `quantity` es `ProductionOrder.quantity` serializada como decimal en texto y `week` no se transforma:

```json
{
  "source": "heilians",
  "orders": [
    {
      "external_order_id": "O-EJEMPLO-001",
      "external_work_ids": ["P-EJEMPLO-001"],
      "parent_code": "ITEM-PADRE-001",
      "week": "31A",
      "quantity": "10.500",
      "client": {"code": "CLIENTE-A", "external_id": "", "name": "Cliente A"}
    },
    {
      "external_order_id": "O-EJEMPLO-002",
      "external_work_ids": ["P-EJEMPLO-002", "P-EJEMPLO-003"],
      "parent_code": "ITEM-PADRE-002",
      "week": "031",
      "quantity": "8.000",
      "client": {"code": "CLIENTE-B", "external_id": "", "name": "Cliente B"}
    }
  ],
  "print_options": {"template_key": "mesa-modern-v1", "label_mode": "components_only"},
  "common": {"line": "", "planner": "", "responsible": ""}
}
```

Ejemplo **propuesto** de respuesta: `{"selection_id":"SEL-EJEMPLO","review_url":"https://edh.ejemplo.local/integraciones/heilians/revisar/SEL-EJEMPLO/","unresolved_routes":[{"external_order_id":"O-EJEMPLO-002","code":"route_ambiguous"}]}`. La URL y el identificador son ficticios.

Respuesta propuesta de selección válida: `201` con `selection_id`, `review_url` y `unresolved_routes` (lista de `external_order_id` con candidatos, sin escoger automáticamente). Para errores de entrada, `422` con `errors: [{external_order_id, external_work_id, field, code, message}]`; por ejemplo `parent_not_found`, `invalid_week`, `invalid_quantity` o `too_many_orders`. Autenticación inválida `401`, servicio sin permiso `403`, selección caducada/cambiada `409`. EDH debe devolver errores sin datos personales ni secretos. La ambigüedad de ruta es resoluble en la pantalla de revisión, no por elección silenciosa en el endpoint.

## 6. Cambios por repositorio y decisiones pendientes

**Heilians:** nueva selección y botón en [templates/operations/heliang.html](templates/operations/heliang.html) o [templates/operations/work_list.html](templates/operations/work_list.html); ruta y vista POST en [operations/urls.py](operations/urls.py) y [operations/views.py](operations/views.py); servicio para leer y validar la carga útil desde [operations/models.py](operations/models.py#L82), pruebas de permisos, cambios de estado y precisión decimal; configuración de destino/autenticación sin valores en el repositorio.

**EDH (según contexto aportado, por verificar allí):** endpoint de recepción firmado, validación de lotes/filas, selección temporal con TTL, pantalla de revisión autenticada, resolución explícita de rutas ambiguas y PDF temporal usando `rutas/services/batch_selection.py`. Mantener controles de aprobación y advertencias de rutas existentes.

**Por decidir con los responsables funcionales y de infraestructura:**

- Confirmar si LINEA de cada orden puede ser el campo común de EDH cuando se mezclan órdenes con líneas diferentes; quién captura PLANNER y RESPONSABLE.
- Confirmar correspondencia de clientes entre sistemas y cómo resolver rutas duplicadas sin planta ni archivo de origen en Heilians.
- Definir URL/DNS HTTPS y conectividad real Heilians→EDH, host permitido por EDH, autenticación de servicio, usuarios autorizados en EDH, TTL de la selección y límites operativos.
- Confirmar diseño y modo de etiquetas por defecto y si una ruta “por revisar” puede generar vista previa sin aprobación.
