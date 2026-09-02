from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ordenes/", views.order_list, name="order-list"),
    path("ordenes/<int:pk>/editar/", views.edit_order, name="edit-order"),
    path("ordenes/<int:pk>/eliminar/", views.delete_order, name="delete-order"),
    path("programas/cargar/", views.load_program, name="load-program"),
    path("programas/carga-masiva/", views.bulk_load_program, name="bulk-load-program"),
    path("programas/plantilla.xlsx", views.download_program_template, name="download-program-template"),
    path("programas/completados.xlsx", views.download_completed_programs, name="download-completed-programs"),
    path("produccion/", views.work_list, name="work-list"),
    path("heliang/", views.heliang, name="heliang"),
    path("tablero-linea/", views.line_dashboard, name="line-dashboard"),
    path("tablero-linea/datos/", views.line_dashboard_data, name="line-dashboard-data"),
    path("tablero-avance/", views.progress_dashboard, name="progress-dashboard"),
    path("tablero-avance/datos/", views.progress_dashboard_data, name="progress-dashboard-data"),
    path("material-en-proceso/", views.process_material, name="process-material"),
    path("produccion/iniciar/", views.start_work, name="start-work"),
    path("produccion/cerrar/", views.close_work, name="close-work"),
    path("inventario/", views.inventory_list, name="inventory-list"),
    path("inventario/sobrante/", views.surplus, name="surplus"),
    path("procesos/", views.process_list, name="process-list"),
    path("reportes/", views.report, name="report"),
    path("reportes/csv/", views.report_csv, name="report-csv"),
]
