# sales/permissions.py
"""
Permissions for the sales app.

Reads from accounts.permissions where possible; adds sales-specific
guards for POS, void, and reports.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import HasBusiness, IsManager


# =====================================================================
# Composite permissions
# =====================================================================
class CanSell(HasBusiness):
    """Anyone in a business can create a sale."""
    message = "You must belong to a business to sell."


class CanVoidSale(IsManager):
    """Only managers/owners can void sales."""
    message = "Manager access required to void a sale."


class CanViewAllSales(IsManager):
    """Only managers/owners can see everyone's sales."""
    message = "Manager access required to view all sales."


# =====================================================================
# Object-level
# =====================================================================
class IsSaleInBusiness(BasePermission):
    """Object-level guard: sale belongs to the user's business."""
    message = "You do not have access to this sale."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return getattr(obj, "business_id", None) == user.business_id


class CanViewSale(BasePermission):
    """
    Salesperson can view their own sales; managers can view all.
    """
    message = "You can only view your own sales."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_manager_or_above:
            return obj.business_id == user.business_id
        return obj.cashier_id == user.pk


class ReadOnlyOrManager(BasePermission):
    """Salespeople read; managers+ write."""
    message = "Manager access required."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not user.business_id:
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_manager_or_above