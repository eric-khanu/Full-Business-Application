"""Tenant + role context for every template."""
from django.core.cache import cache

from .models import Business


def _get_business(user):
    if not user or not user.is_authenticated:
        return None
    if not getattr(user, "business_id", None):
        return None
    return user.business  # cached on the instance after first access


def business_context(request):
    """Tenant + role flags. Skips non-HTML paths."""
    if request.path.startswith(("/api/", "/static/", "/media/")):
        return {}

    user = getattr(request, "user", None)
    biz = _get_business(user)

    if not biz:
        return {
            "current_business": None,
            "current_user_role": None,
            "is_owner": False,
            "is_manager_or_above": False,
            "is_manager": False,
            "is_salesperson": False,
            "business_currency": None,
        }

    return {
        "current_business": biz,
        "current_user_role": user.role,
        "is_owner": user.is_owner,
        "is_manager_or_above": user.is_manager_or_above,
        "is_manager": user.is_manager,
        "is_salesperson": user.is_salesperson,
        "business_currency": biz.currency,
    }


def bootstrap_state(request):
    """True if no Business exists yet. Cached to avoid per-request queries."""
    exists = cache.get("bootstrap_state_exists")
    if exists is None:
        exists = Business.objects.exists()
        cache.set("bootstrap_state_exists", exists, timeout=300)
    return {"business_exists": exists}