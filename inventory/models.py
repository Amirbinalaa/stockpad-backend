import uuid

from django.conf import settings
from django.db import models


class Material(models.Model):
    UNIT_KG = "kg"
    UNIT_LITER = "L"
    UNIT_PCS = "pcs"
    UNIT_METER = "m"

    UNIT_CHOICES = [
        (UNIT_KG, "Kilogram"),
        (UNIT_LITER, "Liter"),
        (UNIT_PCS, "Pieces"),
        (UNIT_METER, "Meter"),
    ]

    CURRENCY_EGP = "EGP"
    CURRENCY_USD = "USD"
    CURRENCY_EUR = "EUR"
    CURRENCY_SAR = "SAR"
    CURRENCY_AED = "AED"

    CURRENCY_CHOICES = [
        (CURRENCY_EGP, "EGP"),
        (CURRENCY_USD, "USD"),
        (CURRENCY_EUR, "EUR"),
        (CURRENCY_SAR, "SAR"),
        (CURRENCY_AED, "AED"),
    ]

    COSTING_MOVING_AVG = "MOVING_AVG"
    COSTING_FIFO = "FIFO"

    COSTING_METHOD_CHOICES = [
        (COSTING_MOVING_AVG, "Moving Average Cost"),
        (COSTING_FIFO, "First-In, First-Out"),
    ]
    # Material image
    image = models.ImageField(upload_to='materials/', null=True, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="materials",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional explicit category; blank values are auto-inferred from the material name.",
    )
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default=UNIT_KG)
    current_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=100,
        help_text="Maximum/reference quantity for stock percentage calculation.")
    low_stock_threshold_percent = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Alert when stock falls below this percentage.",
    )
    reorder_point = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Safety stock threshold — trigger reorder when available stock falls to or below this quantity.",
    )
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_EGP,
    )
    costing_method = models.CharField(
        max_length=12,
        choices=COSTING_METHOD_CHOICES,
        default=COSTING_MOVING_AVG,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "name")]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class StockTransaction(models.Model):
    TYPE_IN = "in"
    TYPE_OUT = "out"

    TYPE_CHOICES = [
        (TYPE_IN, "IN"),
        (TYPE_OUT, "OUT"),
    ]

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="transactions", db_index=True)
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transactions",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["material", "created_at"]),
            models.Index(fields=["type"]),
        ]


class MaterialRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    ]

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="requests", db_index=True)
    requester_id = models.CharField(max_length=255)
    requester_email = models.EmailField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    idempotency_key = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Client-generated UUID to prevent duplicate submissions on retry.",
    )
    webhook_url = models.URLField(max_length=500)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_requests",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["material", "status"]),
        ]

    def __str__(self) -> str:
        return f"Request for {self.material.name} ({self.status})"


class EngineerConnection(models.Model):
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connected_engineers",
        db_index=True,
    )
    engineer_email = models.EmailField(
        unique=True,
        db_index=True,
        help_text="The email of the engineer allowed to access this warehouse.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["engineer_email"]),
            models.Index(fields=["manager", "is_active"]),
        ]

    def __str__(self):
        return f"{self.engineer_email} -> {self.manager.username}"


class WebhookDeliveryLog(models.Model):
    """
    Dead-letter log for permanently failed outbound webhook deliveries.
    Persists when a Celery task exhausts all retries without successfully
    delivering to Site B — prevents silent status drift.
    """
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_FAILED, "Failed"),
    ]

    material_request = models.ForeignKey(
        MaterialRequest,
        on_delete=models.CASCADE,
        related_name="webhook_logs",
        null=True,
        blank=True,
        db_index=True,
    )
    webhook_url = models.URLField(max_length=500)
    payload = models.JSONField()
    event_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Unique event identifier for deduplication on Site B.",
    )
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_FAILED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"WebhookDeliveryLog [{self.status}] -> {self.webhook_url} @ {self.created_at}"


class Product(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    description = models.TextField(blank=True)
    # Reuses the same upload pipeline (MEDIA_ROOT / media/ directory) as Material.image
    photo = models.ImageField(upload_to="products/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"


class ProductMaterial(models.Model):
    """
    One line in a Product's Bill of Materials (BOM).
    Quantity is per finished unit of the product.
    PROTECT on material: deleting a material that is referenced in any BOM
    requires explicit handling first — no silent cascade.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="bom_lines",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="bom_lines",
    )
    # Fractional quantities are valid (e.g. 0.5 kg per unit)
    quantity_per_unit = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ("product", "material")
        indexes = [
            models.Index(fields=["product"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.product.name} — {self.material.name} × {self.quantity_per_unit}"
        )


from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete], sender=Material)
@receiver([post_save, post_delete], sender=StockTransaction)
@receiver([post_save, post_delete], sender=EngineerConnection)
def _catalog_invalidation_signal(sender, instance, **kwargs):
    try:
        from django.core.cache import cache
        version = cache.get("catalog_cache_version", 1)
        cache.set("catalog_cache_version", version + 1, timeout=None)
    except Exception:
        pass

