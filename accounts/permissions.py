from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Business, User


# =====================================================================
# Django view decorators
# =====================================================================
def role_required(*allowed_roles):
    """Restrict a view to specific roles."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.business_id:
                logout(request)
                messages.error(
                    request,
                    "Your account is not linked to a business.",
                )
                return redirect("accounts:login")
            if user.role not in allowed_roles:
                raise PermissionDenied(
                    "You do not have permission for this action."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


owner_required = role_required(User.Role.OWNER)
manager_required = role_required(User.Role.OWNER, User.Role.MANAGER)
salesperson_required = role_required(
    User.Role.OWNER, User.Role.MANAGER, User.Role.SALESPERSON,
)


# =====================================================================
# CBV mixins
# =====================================================================
class _BusinessRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return bool(u.is_authenticated and u.business_id)

    def handle_no_permission(self):
        u = self.request.user
        if u.is_authenticated and not u.business_id:
            logout(self.request)
            messages.error(self.request, "Your account is not linked to a business.")
            return redirect("accounts:login")
        return super().handle_no_permission()


class OwnerRequiredMixin(_BusinessRequiredMixin):
    def test_func(self):
        u = self.request.user
        return bool(u.is_authenticated and u.business_id and u.is_owner)


class ManagerRequiredMixin(_BusinessRequiredMixin):
    def test_func(self):
        u = self.request.user
        return bool(u.is_authenticated and u.business_id and u.is_manager_or_above)


# =====================================================================
# DRF permission classes (kept — useful if you add JSON endpoints later)
# =====================================================================
class HasBusiness(BasePermission):
    message = "You must belong to a business."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.business_id)


class IsOwner(BasePermission):
    message = "Owner access required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_owner)


class IsManager(BasePermission):
    message = "Manager access required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_manager_or_above)


class CanSell(BasePermission):
    message = "You do not have permission to perform sales actions."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated
                    and (u.is_manager_or_above or u.is_salesperson))


IsSalesperson = CanSell


class IsSelfOrManager(BasePermission):
    message = "You can only modify your own profile."

    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_manager_or_above:
            return True
        target = getattr(obj, "user", obj)
        return target == u


class IsSameBusiness(BasePermission):
    message = "You do not have access to this resource."

    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated or not u.business_id:
            return False
        if u.is_superuser:
            return True
        if isinstance(obj, Business):
            return obj.pk == u.business_id
        return getattr(obj, "business_id", None) == u.business_id


class ReadOnlyOrManager(BasePermission):
    message = "Manager access required for write operations."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return u.is_manager_or_above