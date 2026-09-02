from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from .models import (AuditEvent, Client, Inventory, InventoryBucket, Machine, Movement,
                     ModuleAccess, Part, Process, ProductionClose, ProductionOrder, WorkInProcess)

admin.site.site_header = "Administración MESA"
admin.site.site_title = "MESA"
admin.site.index_title = "Catálogos y operaciones"

class ModuleAccessInline(admin.StackedInline):
    model = ModuleAccess
    can_delete = False
    extra = 0

    def get_readonly_fields(self, request, obj=None):
        return () if request.user.is_superuser else ("payroll_number",)


User = get_user_model()
admin.site.unregister(User)


class MesaUserCreationForm(UserCreationForm):
    payroll_number = forms.CharField(label="Número de nómina", max_length=30)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "payroll_number")

    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if ModuleAccess.objects.filter(payroll_number=value).exists():
            raise forms.ValidationError("Este número de nómina ya está asignado.")
        return value

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            access, _ = ModuleAccess.objects.get_or_create(user=user)
            access.payroll_number = self.cleaned_data["payroll_number"]
            access.save(update_fields=["payroll_number"])
        return user


@admin.register(User)
class MesaUserAdmin(UserAdmin):
    add_form = MesaUserCreationForm
    add_fieldsets = (
        (None, {"classes": ("wide",),
                "fields": ("username", "payroll_number", "password1", "password2")}),
    )
    inlines = (ModuleAccessInline,)
    list_display = ("username", "payroll", "first_name", "last_name", "is_staff", "is_active")

    @admin.display(description="Nómina", ordering="module_access__payroll_number")
    def payroll(self, obj):
        return getattr(obj.module_access, "payroll_number", None)

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

