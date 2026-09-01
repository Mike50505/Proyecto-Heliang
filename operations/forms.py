from django import forms
from .models import Employee, Machine, Part, Process, ProductionOrder, WorkInProcess


class OrderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.folio} · {obj.program} · {obj.part.number} · saldo {obj.remaining_quantity}"


class WorkChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (f"{obj.folio} · {obj.order.program} · {obj.order.part.number} · "
                f"{obj.machine.code} · saldo {obj.remaining_quantity}")


class ProgramOrderForm(forms.Form):
    payroll_number = forms.CharField(label="N.º de nómina")
    client = forms.CharField(label="Cliente", max_length=120)
    part_number = forms.CharField(label="N.º de parte", max_length=80)
    program = forms.CharField(label="Programa / orden del cliente", max_length=80)
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    required_date = forms.DateField(label="Fecha de entrega", required=False,
                                    widget=forms.DateInput(attrs={"type": "date"}))
    line = forms.CharField(label="Línea del cliente", max_length=80, required=False)
    comment = forms.CharField(label="Comentarios", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))

    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value


class BulkProgramForm(forms.Form):
    payroll_number = forms.CharField(label="N.º de nómina")
    file = forms.FileField(label="Archivo Excel (.xlsx)",
                           widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))

    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value

    def clean_file(self):
        value = self.cleaned_data["file"]
        if not value.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Selecciona un archivo .xlsx.")
        if value.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar 10 MB.")
        return value


class SurplusMovementForm(forms.Form):
    RECEIVE = "RECEIVE"
    ALLOCATE = "ALLOCATE"
    payroll_number = forms.CharField(label="N.º de nómina")
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

    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("action") == self.ALLOCATE and not data.get("program", "").strip():
            self.add_error("program", "Indica el programa al que se cargará el sobrante.")
        return data


class ProcessMovementForm(forms.Form):
    payroll_number = forms.CharField(label="N.º de nómina")
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

    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("source_process") == data.get("destination_process"):
            self.add_error("destination_process", "El proceso destino debe ser diferente al origen.")
        return data


class StartProductionForm(forms.Form):
    order = OrderChoiceField(label="Orden abierta", queryset=ProductionOrder.objects.none())
    machine = forms.ModelChoiceField(label="Máquina disponible", queryset=Machine.objects.none())
    payroll_number = forms.CharField(label="Nómina")
    quantity = forms.DecimalField(label="Cantidad", min_value=0.001, decimal_places=3)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).select_related("part")
        occupied = WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).values("machine_id")
        self.fields["machine"].queryset = Machine.objects.filter(active=True).exclude(pk__in=occupied)
    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value


class CloseProductionForm(forms.Form):
    work_item = WorkChoiceField(label="Orden procesando", queryset=WorkInProcess.objects.none())
    payroll_number = forms.CharField(label="Nómina")
    quantity = forms.DecimalField(label="Cantidad terminada", min_value=0.001, decimal_places=3)
    comment = forms.CharField(label="Comentario", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_item"].queryset = WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).select_related("order", "machine")
    def clean_payroll_number(self):
        value = self.cleaned_data["payroll_number"].strip()
        if not Employee.objects.filter(payroll_number=value, active=True).exists():
            raise forms.ValidationError("La nómina no está registrada o está inactiva.")
        return value
