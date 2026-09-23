from decimal import Decimal
from datetime import timedelta
from hashlib import sha256
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from .formatting import format_diameter_fraction
from .models import (Client, LoginThrottle, Machine, Part, Process,
                     ProductionOrder, WorkInProcess)


class ThrottledAuthenticationForm(AuthenticationForm):
    max_attempts = 5
    window = timedelta(minutes=15)

    def _key(self):
        username = str(self.data.get("username", "")).strip().casefold()
        address = self.request.META.get("REMOTE_ADDR", "") if self.request else ""
        return sha256(f"login:{address}\0{username}".encode()).hexdigest()

    def clean(self):
        key = self._key()
        now = timezone.now()
        with transaction.atomic():
            throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(
                key=key, defaults={"window_started_at": now})
            if throttle.blocked_until and throttle.blocked_until > now:
                raise forms.ValidationError(
                    "Demasiados intentos. Espera 15 minutos antes de volver a intentar.",
                    code="login_throttled",
                )
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            with transaction.atomic():
                throttle = LoginThrottle.objects.select_for_update().get(key=key)
                if now - throttle.window_started_at >= self.window:
                    throttle.attempts = 1
                    throttle.window_started_at = now
                    throttle.blocked_until = None
                else:
                    throttle.attempts += 1
                    if throttle.attempts >= self.max_attempts:
                        throttle.blocked_until = now + self.window
                throttle.save(update_fields=["attempts", "window_started_at", "blocked_until"])
            raise
        LoginThrottle.objects.filter(key=key).delete()
        return cleaned


class OrderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        diameter = (f" · diámetro {format_diameter_fraction(obj.part.diameter)}"
                    if obj.part.diameter else "")
        return (f"{obj.folio} · {obj.program} · {obj.part.number}{diameter}"
                f" · saldo {obj.remaining_quantity}")


    def label_from_instance(self, obj):
        diameter = (f" · diámetro {format_diameter_fraction(obj.part.diameter)}"
                    if obj.part.diameter else "")
        priority = f"PRIORIDAD {obj.priority:02d} · " if obj.priority else ""
        return f"{priority}{obj.folio} · {obj.program} · {obj.part.number}{diameter} · saldo {obj.remaining_quantity}"


class WorkChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (f"{obj.folio} · {obj.order.program} · {obj.order.part.number} · "
                f"{obj.machine.code} · saldo {obj.remaining_quantity}")


class ProgramOrderForm(forms.Form):
    client = forms.CharField(label="Cliente", max_length=120)
    part_number = forms.CharField(label="N.º de parte", max_length=80)
    program = forms.CharField(label="Programa / orden del cliente", max_length=80)
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    required_date = forms.DateField(label="Fecha de entrega", required=False,
                                    widget=forms.DateInput(attrs={"type": "date"}))
    line = forms.CharField(label="Línea del cliente", max_length=80, required=False)
    priority = forms.IntegerField(label="Prioridad", min_value=1, required=False,
                                  help_text="1 es la prioridad mÃ¡s alta.")
    comment = forms.CharField(label="Comentarios", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))


class ProductionOrderEditForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        fields = ("program", "part", "quantity", "required_date", "line", "priority")
        widgets = {"required_date": forms.DateInput(attrs={"type": "date"})}
        labels = {
            "program": "Semana / orden de producción", "part": "Número de parte",
            "quantity": "Cantidad total", "required_date": "Fecha requerida",
            "line": "Línea del cliente",
        }

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        self.committed_quantity = (instance.quantity - instance.remaining_quantity
                                   if instance and instance.pk else Decimal("0"))
        super().__init__(*args, **kwargs)

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < self.committed_quantity:
            raise forms.ValidationError(
                f"La cantidad no puede ser menor que {self.committed_quantity:g}; esa cantidad ya fue asignada.")
        return quantity

    def clean_part(self):
        part = self.cleaned_data["part"]
        if (self.instance.pk and part.pk != self.instance.part_id and
                self.instance.work_items.exists()):
            raise forms.ValidationError(
                "No se puede cambiar la pieza de una orden que ya tiene producción.")
        return part

class BulkProgramForm(forms.Form):
    file = forms.FileField(label="Archivo Excel (.xlsx)",
                           widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))

    def clean_file(self):
        value = self.cleaned_data["file"]
        if not value.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Selecciona un archivo .xlsx.")
        if value.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar 10 MB.")
        return value


class UniversePartForm(forms.ModelForm):
    class Meta:
        model = Part
        fields = ("number", "client", "diameter", "unit_weight_kg")
        labels = {"number": "N.º de parte", "client": "Cliente",
                  "diameter": "Diámetro", "unit_weight_kg": "Peso unitario (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.order_by("name")


class UniverseImportForm(forms.Form):
    file = forms.FileField(label="Archivo Excel del Universo (.xlsx)",
                           widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))

    def clean_file(self):
        value = self.cleaned_data["file"]
        if not value.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Selecciona un archivo .xlsx.")
        if value.size > 20 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar 20 MB.")
        return value


class SurplusMovementForm(forms.Form):
    RECEIVE = "RECEIVE"
    ALLOCATE = "ALLOCATE"
    action = forms.ChoiceField(label="Movimiento", choices=[
        (RECEIVE, "Recibir material sobrante"),
        (ALLOCATE, "Cargar sobrante a programa"),
    ])
    part = forms.ModelChoiceField(label="N.º de parte", queryset=Part.objects.none())
    program = forms.CharField(label="Programa destino", max_length=100, required=False)
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    comment = forms.CharField(label="Comentarios", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["part"].queryset = Part.objects.order_by("number")

    def clean(self):
        data = super().clean()
        if data.get("action") == self.ALLOCATE and not data.get("program", "").strip():
            self.add_error("program", "Indica el programa al que se cargará el sobrante.")
        return data


class ProcessMovementForm(forms.Form):
    part = forms.ModelChoiceField(label="N.º de parte", queryset=Part.objects.none())
    source_process = forms.ModelChoiceField(label="Proceso que envía", queryset=Process.objects.none())
    destination_process = forms.ModelChoiceField(label="Proceso que recibe", queryset=Process.objects.none())
    program = forms.CharField(label="Programa", max_length=100)
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    comment = forms.CharField(label="Comentarios", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["part"].queryset = Part.objects.order_by("number")
        processes = Process.objects.filter(active=True).order_by("position", "name")
        self.fields["source_process"].queryset = processes
        self.fields["destination_process"].queryset = processes

    def clean(self):
        data = super().clean()
        if data.get("source_process") == data.get("destination_process"):
            self.add_error("destination_process", "El proceso destino debe ser diferente al origen.")
        return data


class StartProductionForm(forms.Form):
    order = OrderChoiceField(label="Orden abierta", queryset=ProductionOrder.objects.none())
    machine = forms.ModelChoiceField(label="Máquina disponible", queryset=Machine.objects.none())
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).select_related("part").annotate(
            priority_sort=Case(When(priority__isnull=True, then=Value(2147483647)), default="priority", output_field=IntegerField())
        ).order_by("priority_sort", "required_date", "created_at")
        occupied = WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).values("machine_id")
        self.fields["machine"].queryset = Machine.objects.filter(active=True).exclude(pk__in=occupied)


class CloseProductionForm(forms.Form):
    work_item = WorkChoiceField(label="Orden procesando", queryset=WorkInProcess.objects.none())
    quantity = forms.DecimalField(label="Cantidad terminada", min_value=0.001, decimal_places=3)
    comment = forms.CharField(label="Comentario", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_item"].queryset = WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).select_related("order", "machine")
