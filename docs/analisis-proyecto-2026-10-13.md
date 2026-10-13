# Análisis del proyecto — 13 de octubre de 2026

Aplicación Django que migra programas, producción, inventario y reportes de Excel a una aplicación web. PostgreSQL en Docker; SQLite para desarrollo. Buena separación de modelos, formularios y servicios; transacciones, auditoría, permisos por módulo y restricciones de integridad.

## Hallazgos anteriores a la implementación de eliminación de cierres

- Alta: devolver producción o cerrar parcialmente puede reabrir órdenes sin validar el límite global de 135000 piezas. Reproducción: 135100 piezas abiertas.
- Alta: el inicio muestra datos de cierres a una cuenta autenticada sin módulos asignados.
- Media: `PartAdmin.search_fields` incluye `description`, eliminado por la migración 0014. Buscar produce `FieldError`.
- Media: `next_folio` usa la fecha UTC de las horas recibidas para producción y cierres, aunque localmente sea el día anterior.
- Media: `import_universe` no cierra el libro leído con openpyxl. Cinco pruebas fallan en Windows al eliminar el archivo bloqueado.
- Defensa de servicios: `move_process_material` permite transferir al mismo proceso; saldo de 10 pasó a 13. El formulario sí impide el caso.
- Mantenimiento: `views.py` supera 1300 líneas; hay límites de registros en tablas y exportaciones sin paginación; README describe puerto 8000 y Compose publica puerto 80.

## Verificación

97 pruebas: 90 pasaron y 7 fallaron. Cinco fallos por bloqueo de archivos Excel; dos por expectativas de HTML (conteo de textos y campos ocultos) que no coinciden con las plantillas. Se repitió fuera del sandbox con el mismo resultado. `manage.py check` sin incidencias; `makemigrations --check --dry-run` sin cambios. Comprobaciones aisladas con SQLite en memoria. No se validó concurrencia real en PostgreSQL ni interfaz en navegador.

Prioridad recomendada: capacidad y permisos; búsqueda, fechas y cierre de archivos; después reorganizar vistas. Este documento conserva el diagnóstico original; no implica que esos hallazgos se hayan corregido.
