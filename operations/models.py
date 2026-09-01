from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True


class Employee(TimeStamped):
    payroll_number = models.CharField("nómina", max_length=30, unique=True)
    name = models.CharField("nombre", max_length=180)
    area = models.CharField(max_length=100, blank=True)
    identifier = models.CharField("identificador", max_length=30, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)
    def __str__(self): return f"{self.payroll_number} - {self.name}"


class Client(TimeStamped):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    def __str__(self): return self.name


class Part(TimeStamped):
    number = models.CharField("número de parte", max_length=80, unique=True)
    description = models.CharField(max_length=250, blank=True)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL)
    diameter = models.CharField(max_length=40, blank=True)
    unit_weight_kg = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))])
    def __str__(self): return self.number


class Process(models.Model):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    position = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    class Meta: ordering = ["position", "name"]
    def __str__(self): return self.name


class Machine(models.Model):
    code = models.CharField(max_length=80, unique=True)
    process = models.ForeignKey(Process, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)
    def __str__(self): return self.code


class Inventory(TimeStamped):
    part = models.OneToOneField(Part, on_delete=models.CASCADE, related_name="inventory")
    surplus = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    real = models.DecimalField(max_digits=14, decimal_places=3, default=0)


class InventoryBucket(TimeStamped):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="buckets")
    kind = models.CharField(max_length=10, choices=[("PROGRAM", "Programa"), ("PROCESS", "Proceso")])
    name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["inventory", "kind", "name"], name="uq_inventory_bucket")]


class ProductionOrder(TimeStamped):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        COMPLETE = "COMPLETE", "Completada"
        CANCELLED = "CANCELLED", "Cancelada"
    folio = models.CharField(max_length=40, unique=True)
    program = models.CharField(max_length=80, db_index=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    remaining_quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    required_date = models.DateField(null=True, blank=True)
    line = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    loaded_by = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)
    def __str__(self): return self.folio


class WorkInProcess(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Procesando"
        CLOSED = "CLOSED", "Cerrada"
    folio = models.CharField(max_length=40, unique=True)
    order = models.ForeignKey(ProductionOrder, on_delete=models.PROTECT, related_name="work_items")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="work_items")
    initial_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    remaining_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    started_at = models.DateTimeField()
    started_by = models.ForeignKey(Employee, null=True, on_delete=models.SET_NULL, related_name="started_work")
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)


class ProductionClose(TimeStamped):
    folio = models.CharField(max_length=40, unique=True)
    work_item = models.ForeignKey(WorkInProcess, on_delete=models.PROTECT, related_name="closes")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    weight_kg = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    closed_at = models.DateTimeField()
    shift = models.CharField(max_length=30, blank=True)
    comment = models.TextField(blank=True)
    closed_by = models.ForeignKey(Employee, null=True, on_delete=models.SET_NULL, related_name="production_closes")
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)


class Movement(TimeStamped):
    class Type(models.TextChoices):
        INVENTORY = "INVENTORY", "Inventario"
        PROGRAM = "PROGRAM", "Programa"
        SURPLUS = "SURPLUS", "Sobrante"
        ORDER = "ORDER", "Orden"
    folio = models.CharField(max_length=50, blank=True, db_index=True)
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    part = models.ForeignKey(Part, null=True, blank=True, on_delete=models.PROTECT)
    source = models.CharField(max_length=100, blank=True)
    destination = models.CharField(max_length=100, blank=True)
    program = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    occurred_at = models.DateTimeField()
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    comment = models.TextField(blank=True)
    legacy_source = models.CharField(max_length=80, blank=True)


class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    entity = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80, blank=True)
    data = models.JSONField(default=dict, blank=True)
    class Meta: ordering = ["-created_at"]


class ModuleAccess(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="module_access", verbose_name="usuario")
    program_loading = models.BooleanField("cargar programas", default=False)
    heliang = models.BooleanField("Heliang · máquinas automáticas", default=False)
    inventory = models.BooleanField("consultar inventario", default=False)
    surplus = models.BooleanField("material sobrante", default=False)
    process_material = models.BooleanField("material en proceso", default=False)
    reports = models.BooleanField("reportes", default=False)
    line_dashboard = models.BooleanField("tablero visual de línea", default=False)

    class Meta:
        verbose_name = "acceso a módulos"
        verbose_name_plural = "accesos a módulos"

    def __str__(self):
        return f"Accesos de {self.user.username}"
