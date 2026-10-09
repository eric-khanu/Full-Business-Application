# inventory/models.py — Sierra Leone pharmacy edition
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# =====================================================================
# Category — supports medicine & non-medicine
# =====================================================================
class Category(models.Model):

    class Kind(models.TextChoices):
        MEDICINE = "medicine", "Medicine"
        OTC = "otc", "Over-the-counter"
        CONSUMABLE = "consumable", "Consumable / Dressing"
        FOOD = "food", "Food & Provisions"
        COSMETIC = "cosmetic", "Cosmetics / Toiletries"
        DEVICE = "device", "Medical Device"
        OTHER = "other", "Other"

    business = models.ForeignKey(
        "accounts.Business", on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=20, choices=Kind.choices,
        default=Kind.MEDICINE,
        help_text="What type of product belongs here.",
    )
    description = models.TextField(blank=True)

    is_controlled = models.BooleanField(
        default=False,
        help_text="Controlled drugs (narcotics, psychotropics) — stricter POS logging.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="unique_category_name_per_business",
            ),
        ]
        indexes = [models.Index(fields=["business", "name"])]

    def __str__(self):
        return self.name


# =====================================================================
# Supplier
# =====================================================================
class Supplier(models.Model):
    business = models.ForeignKey(
        "accounts.Business", on_delete=models.CASCADE,
        related_name="suppliers",
    )
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    license_number = models.CharField(
        max_length=50, blank=True,
        help_text="PBSL wholesaler / distributor licence number.",
    )
    tax_id = models.CharField(max_length=50, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["business", "name"]),
            models.Index(fields=["business", "is_active"]),
        ]

    def __str__(self):
        return self.name


# =====================================================================
# Product — medicine OR non-medicine
# =====================================================================
class Product(models.Model):

    class Form(models.TextChoices):
        # Medicines
        TABLET = "tablet", "Tablet"
        CAPSULE = "capsule", "Capsule"
        SYRUP = "syrup", "Syrup"
        SUSPENSION = "suspension", "Suspension"
        INJECTION = "injection", "Injection"
        CREAM = "cream", "Cream"
        OINTMENT = "ointment", "Ointment"
        DROPS = "drops", "Drops"
        INHALER = "inhaler", "Inhaler"
        SUPPOSITORY = "suppository", "Suppository"
        SACHET = "sachet", "Sachet"
        # Non-medicine
        PIECE = "piece", "Piece"
        PACK = "pack", "Pack"
        BOTTLE = "bottle", "Bottle"
        TIN = "tin", "Tin"
        BAG = "bag", "Bag"
        BOX = "box", "Box"
        OTHER = "other", "Other"

    business = models.ForeignKey(
        "accounts.Business", on_delete=models.CASCADE,
        related_name="products",
    )

    # ---- Identifiers ----
    sku = models.CharField(
        max_length=50, blank=True,
        help_text="Auto-generated if left blank.",
    )
    barcode = models.CharField(max_length=50, blank=True, null=True)

    # ---- Naming ----
    name = models.CharField(
        max_length=200,
        help_text="Brand name (medicines) or product name (non-medicines).",
    )
    strength = models.CharField(
        max_length=50, blank=True,
        help_text="Dosage strength, e.g. '500 mg'.",
    )
    form = models.CharField(
        max_length=20, choices=Form.choices, default=Form.TABLET,
    )

    # ---- Classification ----
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="products",
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="products",
    )

    image = models.ImageField(upload_to="products/", blank=True, null=True)

    # ---- Pricing (SLE) ----
    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Cost per selling unit, in Leones.",
    )
    selling_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Retail price per selling unit, in Leones.",
    )

    # ---- Pack info ----
    pack_size = models.PositiveIntegerField(
        default=1,
        help_text="Selling units per pack (e.g. 10 tablets per strip).",
    )
    unit = models.CharField(
        max_length=20, default="tablet",
        help_text="Selling unit: tablet, ml, piece, tin, etc.",
    )

    # ---- Medicine flags ----
    is_prescription = models.BooleanField(
        default=False,
        help_text="Prescription-only (Rx) medicine.",
    )
    is_controlled = models.BooleanField(
        default=False,
        help_text="Controlled substance — extra logging at POS.",
    )
    is_medicine = models.BooleanField(
        default=True,
        help_text="Uncheck for food stuffs, cosmetics, provisions, etc.",
    )

    # ---- Stock ----
    quantity = models.PositiveIntegerField(
        default=0,
        help_text="Current on-hand quantity in selling units.",
    )
    reorder_level = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    # ---- Expiry ----
    expiry_date = models.DateField(
        null=True, blank=True,
        help_text="Leave blank if the product does not expire.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "sku"],
                name="unique_sku_per_business",
            ),
            # FIX: ensure barcodes stay unique per business
            models.UniqueConstraint(
                fields=["business", "barcode"],
                condition=models.Q(barcode__isnull=False) & ~models.Q(barcode=""),
                name="unique_barcode_per_business",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "name"]),
            models.Index(fields=["business", "sku"]),
            models.Index(fields=["business", "barcode"]),       # FIX: added
            models.Index(fields=["business", "is_active"]),
            models.Index(fields=["business", "is_medicine"]),
            models.Index(fields=["business", "expiry_date"]),
            # FIX: removed `generic_name` index — field doesn't exist
        ]

    def __str__(self):
        if self.strength:
            return f"{self.name} {self.strength} ({self.sku})"
        return f"{self.name} ({self.sku})"

    # ---------------------------------------------------------------
    # Auto-generation of SKU + barcode
    # ---------------------------------------------------------------
    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        if update_fields is None:
            # Full save — generate as needed
            if not self.sku:
                self.sku = self._generate_sku()
            if not self.barcode:
                self.barcode = self._generate_barcode()
        else:
            # Partial save — only generate if the field is in update_fields
            update_fields = set(update_fields)
            if "sku" in update_fields and not self.sku:
                self.sku = self._generate_sku()
            if "barcode" in update_fields and not self.barcode:
                self.barcode = self._generate_barcode()

        super().save(*args, **kwargs)

    @staticmethod
    def _slug_prefix(value: str, length: int = 3) -> str:
        """First N alphanumeric chars of a value, uppercased, X-padded."""
        if not value:
            return "X" * length
        cleaned = "".join(c for c in value.upper() if c.isalnum())
        return cleaned[:length].ljust(length, "X")

    def _generate_sku(self) -> str:
        """
        SKU format: BUS-CAT-SEQ5.
        Scans existing SKUs for this business and uses max+1, retrying on collision.
        """
        bus = self._slug_prefix(self.business.name if self.business_id else "BUS")
        cat = self._slug_prefix(self.category.name if self.category_id else "GEN")

        existing = set(
            Product.objects
            .filter(business_id=self.business_id)
            .exclude(pk=self.pk)
            .values_list("sku", flat=True)
        )

        max_seq = 0
        for sku in existing:
            try:
                seq = int(sku.rsplit("-", 1)[-1])
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, AttributeError):
                continue

        candidate = f"{bus}-{cat}-{max_seq + 1:05d}"
        while candidate in existing:
            max_seq += 1
            candidate = f"{bus}-{cat}-{max_seq + 1:05d}"
        return candidate

    def _generate_barcode(self) -> str:
        """
        Barcode format: 2 + BIZ5 + SEQ6 + CHECK (EAN-13 style).
        Guaranteed unique per business: increments until a free slot is found.
        """
        biz_part = f"{self.business_id or 0:05d}"

        # Start from the highest existing sequence for this business
        existing = set(
            Product.objects
            .filter(business_id=self.business_id)
            .exclude(pk=self.pk)
            .values_list("barcode", flat=True)
        )

        seq = 0
        while True:
            seq += 1
            payload = f"2{biz_part}{seq:06d}"
            total = 0
            for i, ch in enumerate(payload):
                weight = 3 if (i % 2 == 1) else 1
                total += int(ch) * weight
            check = (10 - (total % 10)) % 10
            candidate = f"{payload}{check}"
            if candidate not in existing:
                return candidate

            
    # ---- Computed ----
    @property
    def is_low_stock(self):
        return self.quantity <= self.reorder_level

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.localdate()

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expiring_soon(self):
        d = self.days_to_expiry
        return d is not None and 0 <= d <= 90

    @property
    def margin(self):
        if not self.selling_price:
            return 0
        return self.selling_price - self.cost_price

    @property
    def margin_percent(self):
        if not self.cost_price:
            return 0
        return round((self.margin / self.cost_price) * 100, 2)

    @property
    def stock_value(self):
        return self.cost_price * self.quantity


# =====================================================================
# StockMovement — audit trail
# =====================================================================
class StockMovement(models.Model):

    class MovementType(models.TextChoices):
        IN = "in", "Received"
        OUT = "out", "Dispensed"
        ADJUST = "adjust", "Adjustment"
        EXPIRED = "expired", "Expired / Disposed"
        RETURN = "return", "Return to supplier"

    business = models.ForeignKey(
        "accounts.Business", on_delete=models.CASCADE,
        related_name="stock_movements",
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        related_name="movements",
    )

    movement_type = models.CharField(
        max_length=10, choices=MovementType.choices,
    )
    quantity = models.IntegerField(
        help_text="Positive = increase, negative = decrease.",
    )
    quantity_before = models.IntegerField(default=0)
    quantity_after = models.IntegerField(default=0)

    reason = models.CharField(max_length=200, blank=True)
    reference = models.CharField(
        max_length=100, blank=True,
        help_text="Sale ref, PO number, prescription ID, etc.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "-created_at"]),
            models.Index(fields=["product", "-created_at"]),
            models.Index(fields=["business", "movement_type"]),
        ]

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} "
            f"{self.quantity} × {self.product.name}"
        )

    def clean(self):
        if self.movement_type == self.MovementType.IN and self.quantity <= 0:
            raise ValidationError(
                {"quantity": "Received must be a positive quantity."}
            )
        if self.movement_type in (
            self.MovementType.OUT,
            self.MovementType.EXPIRED,
            self.MovementType.RETURN,     # FIX: added — returns are outbound
        ) and self.quantity >= 0:
            raise ValidationError(
                {"quantity": f"{self.get_movement_type_display()} "
                             f"must be a negative quantity."}
            )