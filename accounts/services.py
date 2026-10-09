"""
Business logic for accounts. Views, forms, and serializers call into here.
Permissions are enforced *inside* the service — not just at the view layer.
"""
import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone

User = get_user_model()

TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
TEMP_PASSWORD_GROUPS = 4
TEMP_PASSWORD_GROUP_LEN = 4


def generate_temporary_password() -> str:
    """Human-readable, unambiguous, cryptographically secure."""
    return "-".join(
        "".join(secrets.choice(TEMP_PASSWORD_ALPHABET)
                for _ in range(TEMP_PASSWORD_GROUP_LEN))
        for _ in range(TEMP_PASSWORD_GROUPS)
    )


# ---------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------
def _assert_can_manage(actor, target: User) -> None:
    """Raise PermissionDenied unless `actor` may manage `target`."""
    if not actor.is_authenticated or not actor.business_id:
        raise PermissionDenied("You must belong to a business.")
    if not actor.is_manager_or_above:
        raise PermissionDenied("Manager access required.")
    if target.business_id != actor.business_id and not actor.is_superuser:
        raise PermissionDenied("Target user is outside your business.")
    if target.is_owner and not actor.is_owner:
        raise PermissionDenied("Only an owner can manage another owner.")
    if target.pk == actor.pk:
        raise PermissionDenied("Use the self-service password change instead.")


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------
def reset_user_password(target: User, *, actor: User) -> str:
    """
    Reset `target`'s password to a fresh temporary password.

    Authorization is enforced here (not just at the call site).
    Returns the plaintext password — display once, never store.
    """
    _assert_can_manage(actor, target)

    temp = generate_temporary_password()
    target.set_password(temp)
    target.must_change_password = True
    target.password_reset_by = actor
    target.password_reset_at = timezone.now()
    target.save(update_fields=[
        "password", "must_change_password",
        "password_reset_by", "password_reset_at", "updated_at",
    ])
    return temp


def mark_password_changed(user: User) -> None:
    """Clear the forced-change flag after the user sets their own password."""
    if not user.must_change_password:
        return
    user.must_change_password = False
    user.save(update_fields=["must_change_password", "updated_at"])