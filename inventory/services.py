# inventory/services.py
"""
Central place for stock mutations.

NEVER modify `Product.quantity` directly — always use these functions,
so every change is:
  1. Atomic (transaction-wrapped)
  2. Audited (StockMovement row created)
  3. Validated (won't go negative)
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Product, StockMovement


class InsufficientStock(Exception):
    """Raised when a stock decrease would leave quantity < 0."""
    pass


# =====================================================================
# Public API — low-level
# =====================================================================
@transaction.atomic
def adjust_stock(
    *,
    product: Product,
    quantity_delta: int,
    movement_type: str,
    reason: str = "",
    reference: str = "",
    actor=None,
) -> StockMovement:
    """
    Adjust a product's stock by `quantity_delta` (positive or negative).

    Returns the StockMovement record.
    Raises InsufficientStock if the resulting quantity would be negative.
    """
    locked = Product.objects.select_for_update().get(pk=product.pk)
    before = locked.quantity
    after = before + quantity_delta

    if after < 0:
        raise InsufficientStock(
            f"Not enough stock for {locked.name}. "
            f"Available: {before}, requested: {abs(quantity_delta)}."
        )

    locked.quantity = after
    locked.save(update_fields=["quantity", "updated_at"])

    return StockMovement.objects.create(
        business=locked.business,
        product=locked,
        movement_type=movement_type,
        quantity=quantity_delta,
        quantity_before=before,
        quantity_after=after,
        reason=reason,
        reference=reference,
        created_by=actor,
    )


# =====================================================================
# Public API — high-level convenience functions
# =====================================================================
@transaction.atomic
def receive_stock(*, product, quantity, reason="", reference="", actor=None):
    """Increase stock (goods received, purchase)."""
    return adjust_stock(
        product=product,
        quantity_delta=abs(quantity),
        movement_type=StockMovement.MovementType.IN,
        reason=reason or "Stock received",
        reference=reference,
        actor=actor,
    )


@transaction.atomic
def dispense_stock(*, product, quantity, reason="", reference="", actor=None):
    """Decrease stock for a sale/dispense."""
    return adjust_stock(
        product=product,
        quantity_delta=-abs(quantity),
        movement_type=StockMovement.MovementType.OUT,
        reason=reason or "Dispensed",
        reference=reference,
        actor=actor,
    )


@transaction.atomic
def remove_stock(*, product, quantity, reason="", reference="", actor=None):
    """Decrease stock for loss / damage / internal use."""
    return adjust_stock(
        product=product,
        quantity_delta=-abs(quantity),
        movement_type=StockMovement.MovementType.ADJUST,
        reason=reason or "Stock removed",
        reference=reference,
        actor=actor,
    )


@transaction.atomic
def dispose_expired(*, product, quantity, reason="", reference="", actor=None):
    """Decrease stock for expired / disposed items."""
    return adjust_stock(
        product=product,
        quantity_delta=-abs(quantity),
        movement_type=StockMovement.MovementType.EXPIRED,
        reason=reason or "Expired / disposed",
        reference=reference,
        actor=actor,
    )


@transaction.atomic
def return_to_supplier(*, product, quantity, reason="", reference="", actor=None):
    """Decrease stock for a return to supplier."""
    return adjust_stock(
        product=product,
        quantity_delta=-abs(quantity),
        movement_type=StockMovement.MovementType.RETURN,
        reason=reason or "Returned to supplier",
        reference=reference,
        actor=actor,
    )


@transaction.atomic
def set_stock(*, product, new_quantity, reason="", reference="", actor=None):
    """
    Set absolute stock level (stock count).
    Creates an ADJUST movement with the delta.
    """
    locked = Product.objects.select_for_update().get(pk=product.pk)
    delta = new_quantity - locked.quantity

    return adjust_stock(
        product=locked,
        quantity_delta=delta,
        movement_type=StockMovement.MovementType.ADJUST,
        reason=reason or "Stock count adjustment",
        reference=reference,
        actor=actor,
    )


# =====================================================================
# Queries — read-only helpers
# =====================================================================
def low_stock_products(business):
    """Active products where quantity <= reorder_level, urgent first."""
    return (
        Product.objects
        .filter(
            business=business,
            is_active=True,
            quantity__lte=F("reorder_level"),
        )
        .select_related("category", "supplier")
        .order_by("quantity", "name")
    )


def expiring_products(business, days: int = 90):
    """Active products expiring within `days` days (includes already-expired)."""
    cutoff = timezone.localdate() + timedelta(days=days)
    return (
        Product.objects
        .filter(
            business=business,
            is_active=True,
            expiry_date__isnull=False,
            expiry_date__lte=cutoff,
        )
        .select_related("category", "supplier")
        .order_by("expiry_date")
    )


def expired_products(business):
    """Active products already past expiry."""
    return (
        Product.objects
        .filter(
            business=business,
            is_active=True,
            expiry_date__isnull=False,
            expiry_date__lt=timezone.localdate(),
        )
        .select_related("category", "supplier")
        .order_by("expiry_date")
    )