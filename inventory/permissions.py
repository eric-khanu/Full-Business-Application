# inventory/permissions.py
"""
DRF permissions specific to inventory.

Reused from accounts.permissions:
  - HasBusiness     — request.user must belong to a business
  - IsManager       — owner or manager
  - IsSameBusiness  — object-level tenant check

Adds:
  - CanManageInventory  — composite: manager + has business
  - CanAdjustStock      — alias for CanManageInventory
  - ReadOnlyOrManager   — salespeople read, managers write
  - IsProductInBusiness — object-level tenant check on Product
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import HasBusiness, IsManager


# =====================================================================
# Composite permissions
# =====================================================================
class CanManageInventory(HasBusiness, IsManager):
    """
    Full inventory CRUD. Owners and managers only.
    """
    message = "Manager access required for inventory changes."


CanAdjustStock = CanManageInventory


# =====================================================================
# Read-only for salespeople, full access for managers
# =====================================================================
class ReadOnlyOrManager(BasePermission):
    """
    Any authenticated user in a business can READ.
    Only managers+ can WRITE.
    """
    message = "Manager access required for inventory changes."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not user.business_id:
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_manager_or_above


# =====================================================================
# Object-level: Product belongs to same business
# =====================================================================
class IsProductInBusiness(BasePermission):
    """
    Object-level guard: the object's business must match the
    request user's business.

    Works for Product, Category, Supplier, StockMovement — any model
    with a `business_id`.
    """
    message = "You do not have access to this item."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated or not user.business_id:
            return False
        if user.is_superuser:
            return True
        return getattr(obj, "business_id", None) == user.business_id


# =====================================================================
# Object-level: StockMovement's product is in same business
# =====================================================================
class IsStockMovementInBusiness(BasePermission):
    """
    Object-level guard for StockMovement — checks via its product.
    """
    message = "You do not have access to this stock movement."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated or not user.business_id:
            return False
        if user.is_superuser:
            return True
        product = getattr(obj, "product", None)
        if not product:
            return False
        return product.business_id == user.business_id