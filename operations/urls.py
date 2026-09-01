from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ordenes/", views.order_list, name="order-list"),
    path("programas/cargar/", views.load_program, name="load-program"),
    path("programas/carga-masiva/", views.bulk_load_program, name="bulk-load-program"),
    path("produccion/", views.work_list, name="work-list"),
    path("heliang/", views.heliang, name="heliang"),
    path("tablero-linea/", views.line_dashboard, name="line-dashboard"),
    path("material-en-proceso/", views.process_material, name="process-material"),
    path("produccion/iniciar/", views.start_work, name="start-work"),
    path("produccion/cerrar/", views.close_work, name="close-work"),
    path("inventario/", views.inventory_list, name="inventory-list"),
    path("inventario/sobrante/", views.surplus, name="surplus"),
    path("procesos/", views.process_list, name="process-list"),
    path("reportes/", views.report, name="report"),
    path("reportes/csv/", views.report_csv, name="report-csv"),
]
