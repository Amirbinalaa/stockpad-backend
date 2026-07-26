from django.db import transaction as db_transaction
from rest_framework import serializers

from .models import Material, StockTransaction, MaterialRequest, EngineerConnection

# Unit → PE catalog category (no DB category field on Material)
_UNIT_CATEGORY_MAP = {
    Material.UNIT_KG: (1, "Raw Materials"),
    Material.UNIT_LITER: (2, "Liquids & Chemicals"),
    Material.UNIT_PCS: (3, "Components & Parts"),
    Material.UNIT_METER: (4, "Structural Materials"),
}
_DEFAULT_CATEGORY = (0, "General Supplies")


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
    cat_id, cat_name = _UNIT_CATEGORY_MAP.get(material.unit, _DEFAULT_CATEGORY)
    return {"id": cat_id, "name": cat_name}, cat_name


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
    class Meta:
        model = Material
        fields = [
            "id",
            "name",
            "unit",
            "current_quantity",
            "max_quantity",
            "low_stock_threshold_percent",
            "cost_price",
            "currency",
            "costing_method",
            "is_active",
            "created_at",
            "updated_at",
            "image",
        ]
        read_only_fields = ["id", "current_quantity", "created_at", "updated_at"]


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
            "unit",
            "initial_quantity",
            "max_quantity",
            "current_quantity",
            "low_stock_threshold_percent",
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


