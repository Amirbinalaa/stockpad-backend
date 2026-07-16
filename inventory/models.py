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

    def __str__(self) -> str:
        return self.name


class StockTransaction(models.Model):
    TYPE_IN = "in"
    TYPE_OUT = "out"

    TYPE_CHOICES = [
        (TYPE_IN, "IN"),
        (TYPE_OUT, "OUT"),
    ]

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MaterialRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    ]

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="requests")
    requester_id = models.CharField(max_length=255)
    requester_email = models.EmailField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    webhook_url = models.URLField(max_length=500)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Request for {self.material.name} ({self.status})"


class EngineerConnection(models.Model):
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connected_engineers",
    )
    engineer_email = models.EmailField(
        unique=True,
        help_text="The email of the engineer allowed to access this warehouse.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.engineer_email} -> {self.manager.username}"