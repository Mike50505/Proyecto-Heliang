from django.contrib import admin
from .models import (AuditEvent, Client, Employee, Inventory, InventoryBucket, Machine, Movement,
                     ModuleAccess, Part, Process, ProductionClose, ProductionOrder, WorkInProcess)

admin.site.site_header = "Administración MESA"
admin.site.site_title = "MESA"
admin.site.index_title = "Catálogos y operaciones"

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("payroll_number", "name", "area", "active")
    search_fields = ("payroll_number", "name")
    list_filter = ("area", "active")

@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("number", "client", "unit_weight_kg")
    search_fields = ("number", "description")
    list_filter = ("client",)

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("folio", "program", "part", "quantity", "remaining_quantity", "status", "required_date")
    search_fields = ("folio", "program", "part__number")
    list_filter = ("status", "required_date")

@admin.register(WorkInProcess)
class WorkInProcessAdmin(admin.ModelAdmin):
    list_display = ("folio", "order", "machine", "remaining_quantity", "status", "started_at")
    search_fields = ("folio", "order__folio", "order__part__number")
    list_filter = ("status", "machine")

@admin.register(ProductionClose)
class ProductionCloseAdmin(admin.ModelAdmin):
    list_display = ("folio", "work_item", "quantity", "weight_kg", "closed_at", "shift")
    search_fields = ("folio", "work_item__folio", "work_item__order__part__number")
    list_filter = ("shift", "closed_at")

for model in [Client, Process, Machine, Inventory, InventoryBucket, Movement, AuditEvent]:
    admin.site.register(model)


@admin.register(ModuleAccess)
class ModuleAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "program_loading", "heliang", "inventory", "surplus",
                    "process_material", "reports", "line_dashboard")
    list_editable = ("program_loading", "heliang", "inventory", "surplus",
                     "process_material", "reports", "line_dashboard")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
