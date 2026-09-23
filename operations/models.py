from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True


class Client(TimeStamped):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    external_id = models.CharField("ID cliente", max_length=30, blank=True, db_index=True)
    def __str__(self): return self.name


class Part(TimeStamped):
    number = models.CharField("número de parte", max_length=80, unique=True)
    in_universe_ramos = models.BooleanField(default=False, db_index=True)
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

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(surplus__gte=0), name="inventory_surplus_nonnegative"),
            models.CheckConstraint(condition=Q(real__gte=0), name="inventory_real_nonnegative"),
        ]


class InventoryBucket(TimeStamped):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="buckets")
    kind = models.CharField(max_length=10, choices=[("PROGRAM", "Programa"), ("PROCESS", "Proceso")])
    name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["inventory", "kind", "name"], name="uq_inventory_bucket"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="bucket_quantity_nonnegative"),
        ]


class ProductionOrder(TimeStamped):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        ALLOCATED = "ALLOCATED", "Asignada"
        COMPLETE = "COMPLETE", "Completada"
        CANCELLED = "CANCELLED", "Cancelada"
    folio = models.CharField(max_length=40, unique=True)
    program = models.CharField(max_length=80, db_index=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    remaining_quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    required_date = models.DateField(null=True, blank=True)
    line = models.CharField(max_length=80, blank=True)
    priority = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    loaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)
    def __str__(self): return self.folio

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="order_quantity_positive"),
            models.CheckConstraint(condition=Q(remaining_quantity__gte=0), name="order_remaining_nonnegative"),
            models.CheckConstraint(condition=Q(remaining_quantity__lte=models.F("quantity")), name="order_remaining_lte_quantity"),
        ]


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
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="started_work")
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["machine"],
                condition=Q(status="ACTIVE"),
                name="uq_active_work_per_machine",
            ),
            models.CheckConstraint(condition=Q(initial_quantity__gt=0), name="work_initial_positive"),
            models.CheckConstraint(condition=Q(remaining_quantity__gte=0), name="work_remaining_nonnegative"),
            models.CheckConstraint(condition=Q(remaining_quantity__lte=models.F("initial_quantity")), name="work_remaining_lte_initial"),
        ]


class ProductionClose(TimeStamped):
    folio = models.CharField(max_length=40, unique=True)
    work_item = models.ForeignKey(WorkInProcess, on_delete=models.PROTECT, related_name="closes")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    weight_kg = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    closed_at = models.DateTimeField()
    shift = models.CharField(max_length=30, blank=True)
    comment = models.TextField(blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="production_closes")
    legacy_id = models.CharField(max_length=80, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="close_quantity_positive"),
            models.CheckConstraint(condition=Q(weight_kg__gte=0), name="close_weight_nonnegative"),
        ]


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
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    comment = models.TextField(blank=True)
    legacy_source = models.CharField(max_length=80, blank=True)


class ProgramImportReceipt(models.Model):
    # Independent of the order so deletion cannot make an imported row new again.
    fingerprint = models.CharField(max_length=64, unique=True)


class FolioCounter(models.Model):
    """Serializes folio allocation independently from business rows."""
    key = models.CharField(max_length=100, unique=True)
    next_value = models.PositiveBigIntegerField(default=1)


class ProgramImportPreview(models.Model):
    token = models.UUIDField(unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    payload = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    blocked_until = models.DateTimeField(null=True, blank=True)


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
    payroll_number = models.CharField("número de nómina", max_length=30, unique=True,
                                      null=True, blank=True)
    program_loading = models.BooleanField("cargar programas", default=False)
    heliang = models.BooleanField("Heliang · máquinas automáticas", default=False)
    inventory = models.BooleanField("consultar inventario", default=False)
    surplus = models.BooleanField("material sobrante", default=False)
    process_material = models.BooleanField("material en proceso", default=False)
    reports = models.BooleanField("reportes", default=False)
    universe = models.BooleanField("consultar Universo Ramos Arizpe", default=False)
    universe_edit = models.BooleanField("editar Universo Ramos Arizpe", default=False)
    universe_import = models.BooleanField("importar Universo Ramos Arizpe", default=False)
    line_dashboard = models.BooleanField("tablero visual de línea", default=False)

    class Meta:
        verbose_name = "acceso a módulos"
        verbose_name_plural = "accesos a módulos"

    def __str__(self):
        return f"Accesos de {self.user.username}"
