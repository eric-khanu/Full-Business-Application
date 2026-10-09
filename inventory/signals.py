# inventory/signals.py
"""
Signals for the inventory app.

Responsibilities:
  - Auto-fill `StockMovement.business` from its product.
  - Enforce sign convention on `StockMovement.quantity`.
  - Detect direct `Product.quantity` edits (dev safety net).
  - Log when a product enters the low-stock zone.

Actual stock mutation lives in `inventory/services.py`, not here.
"""

import logging

from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Product, StockMovement

logger = logging.getLogger(__name__)


# =====================================================================
# StockMovement — auto-fill business from product
# =====================================================================
@receiver(
    pre_save,
    sender=StockMovement,
    dispatch_uid="inventory.stock_movement_fill_business",
)
def stock_movement_fill_business(sender, instance, **kwargs):
    """Ensure business matches the product's business."""
    if instance.product_id:
        product_biz_id = instance.product.business_id
        if instance.business_id != product_biz_id:
            instance.business_id = product_biz_id


# =====================================================================
# StockMovement — enforce sign convention (raise, don't flip)
# =====================================================================
@receiver(
    pre_save,
    sender=StockMovement,
    dispatch_uid="inventory.stock_movement_validate_sign",
)
def stock_movement_validate_sign(sender, instance, **kwargs):
    """
    Sign convention:
      - IN (received)          -> quantity > 0
      - OUT (dispensed)        -> quantity < 0
      - EXPIRED (disposed)     -> quantity < 0
      - RETURN (to supplier)   -> quantity < 0
      - ADJUST (count/other)   -> either sign
    """
    mt = instance.movement_type
    q = instance.quantity

    if mt == StockMovement.MovementType.IN and q <= 0:
        raise ValidationError(
            {"quantity": "Received movements must have a positive quantity."}
        )
    if mt in (
        StockMovement.MovementType.OUT,
        StockMovement.MovementType.EXPIRED,
        StockMovement.MovementType.RETURN,
    ) and q >= 0:
        raise ValidationError(
            {"quantity": f"{instance.get_movement_type_display()} movements "
                         f"must have a negative quantity."}
        )


# =====================================================================
# Product — detect direct quantity edits (dev safety net)
# =====================================================================
@receiver(
    pre_save,
    sender=Product,
    dispatch_uid="inventory.product_detect_direct_quantity_edit",
)
def product_detect_direct_quantity_edit(sender, instance, **kwargs):
    """
    Warn (don't block) if `quantity` is changed directly without going
    through inventory.services.

    Only fires when the product already exists and the caller didn't
    explicitly flag the update. `adjust_stock()` sets `_skip_qty_check`
    on the instance so this is bypassed.
    """
    if not instance.pk:
        return
    if getattr(instance, "_skip_qty_check", False):
        return

    try:
        old_qty = Product.objects.only("quantity").get(pk=instance.pk).quantity
    except Product.DoesNotExist:
        return

    if old_qty != instance.quantity:
        logger.warning(
            "Product.quantity changed directly — bypasses services.py.",
            extra={
                "product_id": instance.pk,
                "product_sku": instance.sku,
                "before": old_qty,
                "after": instance.quantity,
            },
        )
        # To hard-block:
        # raise ValidationError(
        #     "Do not edit Product.quantity directly. "
        #     "Use inventory.services.adjust_stock()."
        # )


# =====================================================================
# Product — low-stock alert on save
# =====================================================================
@receiver(
    post_save,
    sender=Product,
    dispatch_uid="inventory.product_low_stock_alert",
)
def product_low_stock_alert(sender, instance, created, **kwargs):
    """
    Log when a product transitions INTO the low-stock zone.

    Doesn't log again while it stays low. Doesn't log when it recovers.
    """
    if created:
        if not instance.is_low_stock:
            return
    else:
        # If we just changed quantity, we can't know the previous state
        # without a query. Only do that query if the product is now low.
        if not instance.is_low_stock:
            return
        try:
            old = Product.objects.only("quantity", "reorder_level").get(pk=instance.pk)
        except Product.DoesNotExist:
            return
        was_low = old.quantity <= old.reorder_level
        if was_low:
            return   # already low, no new alert

    logger.info(
        "Low stock: %s (%s) — qty=%s, reorder=%s",
        instance.name, instance.sku,
        instance.quantity, instance.reorder_level,
        extra={
            "business_id": instance.business_id,
            "product_id": instance.pk,
            "product_sku": instance.sku,
            "quantity": instance.quantity,
            "reorder_level": instance.reorder_level,
        },
    )