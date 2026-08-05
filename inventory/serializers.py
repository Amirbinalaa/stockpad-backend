import json
from decimal import Decimal

from django.db import transaction as db_transaction
from rest_framework import serializers

from .material_categories import resolve_material_category_for_instance
from .models import Material, StockTransaction, MaterialRequest, EngineerConnection, Product, ProductMaterial


def normalize_engineer_email(email):
    return (email or "").strip().lower()


def resolve_stock_status(material):
    qty = float(material.current_quantity or 0)
    if qty <= 0:
        return "out_of_stock"
    threshold_percent = material.low_stock_threshold_percent
    max_qty = float(material.max_quantity or 0)
    if threshold_percent and max_qty > 0:
        threshold_value = max_qty * (float(threshold_percent) / 100.0)
        if qty <= threshold_value:
            return "low_stock"
    return "in_stock"


def resolve_material_category(material):
    return resolve_material_category_for_instance(material)


def build_engineer_catalog_item(material):
    """Flat PE-facing catalog payload with quantity aliases and category metadata."""
    qty = float(material.current_quantity or 0)
    category, category_name = resolve_material_category(material)
    return {
        "id": material.id,
        "name": material.name,
        "unit": material.unit,
        "quantity": qty,
        "quantity_available": qty,
        "current_quantity": qty,
        "stock_status": resolve_stock_status(material),
        "category_name": category_name,
        "category": category,
        "low_stock_threshold_percent": material.low_stock_threshold_percent,
        "max_quantity": float(material.max_quantity or 0),
        "is_active": material.is_active,
    }


class MaterialSerializer(serializers.ModelSerializer):
    resolved_category = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Material
        fields = [
            "id",
            "name",
            "category",
            "resolved_category",
            "unit",
            "current_quantity",
            "max_quantity",
            "low_stock_threshold_percent",
            "reorder_point",
            "cost_price",
            "currency",
            "costing_method",
            "is_active",
            "created_at",
            "updated_at",
            "image",
        ]
        read_only_fields = ["id", "current_quantity", "created_at", "updated_at", "resolved_category"]

    def get_resolved_category(self, obj):
        _, name = resolve_material_category_for_instance(obj)
        return name


class MaterialCreateSerializer(serializers.ModelSerializer):
    initial_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        write_only=True,
    )

    class Meta:
        model = Material
        fields = [
            "id",
            "name",
            "category",
            "unit",
            "initial_quantity",
            "max_quantity",
            "current_quantity",
            "low_stock_threshold_percent",
            "reorder_point",
            "cost_price",
            "currency",
            "costing_method",
            "updated_at",
        ]
    read_only_fields = ["id", "current_quantity", "updated_at"]

    def create(self, validated_data):
        initial_quantity = validated_data.pop("initial_quantity")
        material = Material.objects.create(
        current_quantity=initial_quantity,
        **validated_data,)
        
        StockTransaction.objects.create(
            material=material,
            type=StockTransaction.TYPE_IN,
            quantity=initial_quantity,
            notes="Initial quantity",
            performed_by=self.context["request"].user if self.context.get("request") else None,
        )
        return material


class StockTransactionSerializer(serializers.ModelSerializer):
    material_name = serializers.ReadOnlyField(source="material.name")
    unit = serializers.ReadOnlyField(source="material.unit")

    class Meta:
        model = StockTransaction
        fields = [
            "id",
            "material",
            "material_name",
            "unit",
            "type",
            "quantity",
            "notes",
            "performed_by",
            "created_at",
        ]
        read_only_fields = ["id", "performed_by", "created_at", "material_name", "unit"]

    def validate(self, attrs):
        material = attrs["material"]
        qty = attrs["quantity"]
        type_ = attrs["type"]

        if qty <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})

        if type_ == StockTransaction.TYPE_OUT and material.current_quantity - qty < 0:
            raise serializers.ValidationError({"quantity": "Not enough stock for this operation."})

        return attrs

    @db_transaction.atomic
    def create(self, validated_data):
        material = validated_data["material"]
        qty = validated_data["quantity"]
        type_ = validated_data["type"]

        if self.context.get("request"):
            validated_data["performed_by"] = self.context["request"].user

        if type_ == StockTransaction.TYPE_IN:
            material.current_quantity += qty
        else:
            material.current_quantity -= qty

        material.save(update_fields=["current_quantity"])
        return super().create(validated_data)


class MaterialRequestSerializer(serializers.ModelSerializer):
    material_name = serializers.ReadOnlyField(source="material.name")
    material_unit = serializers.ReadOnlyField(source="material.unit")

    class Meta:
        model = MaterialRequest
        fields = [
            "id",
            "material",
            "material_name",
            "material_unit",
            "requester_id",
            "requester_email",
            "quantity",
            "reason",
            "status",
            "webhook_url",
            "review_notes",
            "reviewed_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "material_name",
            "material_unit",
            "status",
            "reviewed_by",
            "created_at",
            "updated_at",
            "idempotency_key",
        ]


class MaterialRequestReviewSerializer(serializers.ModelSerializer):
    """Writable status/review_notes for PATCH review endpoint only."""

    status = serializers.ChoiceField(
        choices=[
            (MaterialRequest.STATUS_APPROVED, "Approved"),
            (MaterialRequest.STATUS_DENIED, "Denied"),
        ]
    )
    review_notes = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = MaterialRequest
        fields = ["status", "review_notes"]


class MaterialRequestCreateSerializer(serializers.ModelSerializer):
    """Used for external creation (Site-to-Site)"""

    class Meta:
        model = MaterialRequest
        fields = [
            "id",
            "material",
            "requester_id",
            "requester_email",
            "quantity",
            "reason",
            "webhook_url",
            "idempotency_key",
        ]
        extra_kwargs = {
            "idempotency_key": {"required": False, "allow_null": True},
        }


class EngineerConnectionSerializer(serializers.ModelSerializer):
    # Override to suppress the DRF auto-added UniqueValidator so our
    # custom create() can handle reactivation of inactive connections.
    engineer_email = serializers.EmailField(
        max_length=254,
        validators=[],   # disable auto UniqueValidator
    )

    class Meta:
        model = EngineerConnection
        fields = ["id", "engineer_email", "is_active", "created_at"]
        read_only_fields = ["id", "is_active", "created_at"]

    def validate_engineer_email(self, value):
        if not value:
            raise serializers.ValidationError("Email is required.")
        return value.strip().lower()

    @db_transaction.atomic
    def create(self, validated_data):
        email = validated_data["engineer_email"]
        manager = self.context["request"].user
        
        # Check if already exists in the system
        connection = EngineerConnection.objects.filter(engineer_email=email).first()
        if connection:
            if connection.is_active:
                raise serializers.ValidationError(
                    {"engineer_email": "This email is already connected."}
                )
            else:
                # Reactivate and associate with the current manager
                connection.manager = manager
                connection.is_active = True
                connection.save(update_fields=["manager", "is_active"])
                return connection
                
        return EngineerConnection.objects.create(
            manager=manager,
            engineer_email=email,
            is_active=True
        )


# ---------------------------------------------------------------------------
# Phase 3 — Product & BOM Serializers
# ---------------------------------------------------------------------------

class MaterialQuickCreateSerializer(serializers.ModelSerializer):
    """
    Dedicated quick-create path for the BOM material search mini-form.
    MaterialCreateSerializer is NOT modified — this class is isolated.

    Differences from MaterialCreateSerializer:
    - initial_quantity is optional (defaults to 0.00) — the user did not
      come from the main Add Material flow, so stock tracking starts at zero.
    - Validates name uniqueness case-insensitively per user to prevent
      duplicates that only differ by casing.
    """
    initial_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        write_only=True,
        default=Decimal("0.00"),
    )

    class Meta:
        model = Material
        fields = ["id", "name", "category", "unit", "initial_quantity", "current_quantity", "updated_at"]
        read_only_fields = ["id", "current_quantity", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        request = self.context.get("request")
        user = request.user if request else None
        if user and Material.objects.filter(user=user, name__iexact=value).exists():
            raise serializers.ValidationError(
                "A material with this name already exists in your catalog."
            )
        return value

    @db_transaction.atomic
    def create(self, validated_data):
        initial_quantity = validated_data.pop("initial_quantity", Decimal("0.00"))
        material = Material.objects.create(
            current_quantity=initial_quantity,
            **validated_data,
        )
        # Always record an initial IN transaction, even for zero-quantity quick-creates.
        StockTransaction.objects.create(
            material=material,
            type=StockTransaction.TYPE_IN,
            quantity=initial_quantity,
            notes="Initial quantity (quick-create)",
            performed_by=self.context["request"].user if self.context.get("request") else None,
        )
        return material


class ProductMaterialSerializer(serializers.ModelSerializer):
    """Serializes one BOM line (read + write)."""
    material_name = serializers.ReadOnlyField(source="material.name")
    material_unit = serializers.ReadOnlyField(source="material.unit")

    class Meta:
        model = ProductMaterial
        fields = ["id", "material", "material_name", "material_unit", "quantity_per_unit"]
        read_only_fields = ["id", "material_name", "material_unit"]

    def validate_quantity_per_unit(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "quantity_per_unit must be greater than zero."
            )
        return value


class ProductSerializer(serializers.ModelSerializer):
    """
    Full Product serializer with nested BOM lines (read and write).

    Photo + BOM in the same multipart request:
    When the client sends a multipart/form-data request (photo upload),
    bom_lines arrives as a JSON-stringified string.  to_internal_value()
    parses it so the rest of the validation pipeline sees a proper list.

    BOM uniqueness:
    Duplicate material IDs within the same payload are caught here, before
    any DB write, so callers receive a clear 400 ValidationError instead of
    a raw IntegrityError.
    """
    bom_lines = ProductMaterialSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "category",
            "unit_of_measure",
            "status",
            "description",
            "photo",
            "bom_lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_internal_value(self, data):
        """
        Handle multipart/form-data requests where bom_lines is a
        JSON-stringified string rather than a native list.
        """
        mutable_data = data.copy() if hasattr(data, "copy") else dict(data)

        raw_bom = mutable_data.get("bom_lines")
        if isinstance(raw_bom, str):
            try:
                parsed = json.loads(raw_bom)
            except (json.JSONDecodeError, ValueError):
                raise serializers.ValidationError(
                    {"bom_lines": "bom_lines must be a valid JSON array."}
                )
            mutable_data["bom_lines"] = parsed

        return super().to_internal_value(mutable_data)

    def validate_bom_lines(self, value):
        """Catch duplicate material IDs in the submitted payload."""
        seen = set()
        for item in value:
            mat = item.get("material")
            mat_id = getattr(mat, "id", mat)  # may be model instance or PK
            if mat_id in seen:
                raise serializers.ValidationError(
                    "Duplicate material detected in BOM lines — each material "
                    "may appear at most once per product."
                )
            seen.add(mat_id)
        return value

    @db_transaction.atomic
    def create(self, validated_data):
        bom_lines_data = validated_data.pop("bom_lines", [])
        product = Product.objects.create(**validated_data)
        for line in bom_lines_data:
            ProductMaterial.objects.create(product=product, **line)
        return product

    @db_transaction.atomic
    def update(self, instance, validated_data):
        bom_lines_data = validated_data.pop("bom_lines", None)

        # Update scalar product fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Full BOM replace only when bom_lines is explicitly present in the payload
        if bom_lines_data is not None:
            instance.bom_lines.all().delete()
            for line in bom_lines_data:
                ProductMaterial.objects.create(product=instance, **line)

        return instance
