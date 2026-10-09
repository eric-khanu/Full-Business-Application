"""
Web views for the accounts app.

Auth, staff CRUD, password reset, profile, business settings, bootstrap.
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    get_user_model, login, logout, update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    BootstrapOwnerForm, BusinessForm, CustomPasswordChangeForm,
    LoginForm, ProfileForm, StaffCreateForm, StaffEditForm,
)
from .models import Business, User
from .permissions import manager_required, owner_required, PermissionDenied
from .services import mark_password_changed, reset_user_password

User = get_user_model()

# Session keys for one-time temp-password display
SESSION_TEMP_PW_USER = "_temp_pw_user_id"
SESSION_TEMP_PW_VALUE = "_temp_pw_value"


# =====================================================================
# Helpers
# =====================================================================
def post_login_redirect(user) -> str:
    """Role-aware landing page with safe fallbacks."""
    if user.is_manager_or_above:
        try:
            return reverse("reports:dashboard")
        except NoReverseMatch:
            pass
    try:
        return reverse("sales:pos")
    except NoReverseMatch:
        pass
    return reverse("accounts:profile")


def _safe_next(request, fallback: str) -> str:
    """Prevent open-redirect via ?next=..."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _consume_temp_password(request):
    """Pop the one-time temp password (if any) from session."""
    user_id = request.session.pop(SESSION_TEMP_PW_USER, None)
    value = request.session.pop(SESSION_TEMP_PW_VALUE, None)
    return user_id, value


# =====================================================================
# Bootstrap (one-time)
# =====================================================================
def setup_owner(request):
    """Public, but self-disables the moment a Business exists."""
    if Business.objects.exists():
        return redirect("accounts:login")

    if settings.SETUP_TOKEN and request.GET.get("token") != settings.SETUP_TOKEN:
        raise Http404

    if request.method == "POST":
        form = BootstrapOwnerForm(request.POST)
        if form.is_valid():
            form.save()
            cache.delete("bootstrap_state_exists")
            messages.success(request, "Business created. Please log in.")
            return redirect("accounts:login")
    else:
        form = BootstrapOwnerForm()
    return render(request, "accounts/setup_owner.html", {"form": form})


# =====================================================================
# Auth
# =====================================================================
def login_view(request):
    if request.user.is_authenticated:
        return redirect(post_login_redirect(request.user))

    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        if not form.cleaned_data.get("remember_me"):
            request.session.set_expiry(0)
        messages.success(
            request,
            f"Welcome back, {user.get_full_name() or user.username}!",
        )
        return redirect(_safe_next(request, post_login_redirect(user)))

    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("accounts:login")


# =====================================================================
# Staff — list
# =====================================================================
@manager_required
def staff_list(request):
    biz = request.user.business
    qs = (
        User.objects
        .filter(business=biz)
        .order_by("first_name", "last_name", "username")
    )

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(employee_id__icontains=q)
        )

    role = request.GET.get("role", "").strip()
    if role:
        qs = qs.filter(role=role)

    status = request.GET.get("status", "").strip()
    if status == "active":
        qs = qs.filter(is_active_staff=True)
    elif status == "inactive":
        qs = qs.filter(is_active_staff=False)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Consume the one-time temp password (set by staff_create)
    temp_password = request.session.pop(SESSION_TEMP_PW_VALUE, None)
    temp_password_user_id = request.session.pop(SESSION_TEMP_PW_USER, None)

    # Look up the new user's name so the banner can say "for John Kamara"
    temp_username = None
    if temp_password_user_id:
        temp_username = (
            User.objects
            .filter(pk=temp_password_user_id, business=biz)
            .values_list("username", flat=True)
            .first()
        )

    return render(request, "accounts/staff_list.html", {
        "staff": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "q": q,
        "role_filter": role,
        "status_filter": status,
        "role_choices": User.Role.choices,
        "counts": {
            "all": User.objects.filter(business=biz).count(),
            "active": User.objects.filter(business=biz, is_active_staff=True).count(),
            "salespersons": User.objects.filter(
                business=biz, role=User.Role.SALESPERSON
            ).count(),
        },
        "can_manage": request.user.is_owner,
        "temp_password": temp_password,
        "temp_username": temp_username,
    })


# =====================================================================
# Staff — create / edit / toggle / delete
# =====================================================================
@owner_required
def staff_create(request):
    if request.method == "POST":
        form = StaffCreateForm(request.POST, actor=request.user)
        if form.is_valid():
            user = form.save()

            # Stash the one-time temp password for the list view to display
            request.session[SESSION_TEMP_PW_USER] = user.pk
            request.session[SESSION_TEMP_PW_VALUE] = form.temp_password

            messages.success(
                request,
                f'Account created for "{user.username}". '
                f"Share the temporary password — it will only be shown once.",
            )
            return redirect("accounts:staff_list")
    else:
        form = StaffCreateForm(actor=request.user)
    return render(request, "accounts/staff_form.html", {
        "form": form,
        "title": "New staff account",
        "submit_label": "Create account",
    })

@manager_required
def staff_edit(request, pk):
    staff = get_object_or_404(User, pk=pk, business=request.user.business)
    if staff.is_owner and not request.user.is_owner:
        raise PermissionDenied

    form = StaffEditForm(
        request.POST or None,
        request.FILES or None,
        instance=staff,
        actor=request.user,
    )
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        messages.success(request, f'"{updated.username}" updated.')
        return redirect("accounts:staff_list")

    return render(request, "accounts/staff_form.html", {
        "form": form,
        "staff": staff,
        "title": f"Edit {staff.get_full_name() or staff.username}",
        "submit_label": "Save changes",
    })


@manager_required
@require_POST
def staff_toggle_active(request, pk):
    staff = get_object_or_404(User, pk=pk, business=request.user.business)

    if staff.pk == request.user.pk:
        messages.error(request, "You can't deactivate yourself.")
        return redirect("accounts:staff_list")

    if staff.is_owner and not request.user.is_owner:
        raise PermissionDenied

    if staff.is_active_staff:
        staff.deactivate()
        state = "deactivated"
    else:
        staff.reactivate()
        state = "activated"

    # HTMX-aware
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "app:message": {
                "message": f'"{staff.username}" {state}.',
                "level": "success",
            }
        })
        return response

    messages.success(request, f'"{staff.username}" {state}.')
    return redirect("accounts:staff_list")


@manager_required
def staff_delete(request, pk):
    staff = get_object_or_404(User, pk=pk, business=request.user.business)

    if staff.pk == request.user.pk:
        messages.error(request, "You can't delete yourself.")
        return redirect("accounts:staff_list")

    if staff.is_owner:
        # One owner per business: delete is never allowed via UI
        messages.error(
            request,
            "You can't delete the owner. Transfer ownership first.",
        )
        return redirect("accounts:staff_list")

    if request.method == "POST":
        username = staff.username
        staff.delete()
        messages.success(request, f'Staff "{username}" deleted.')
        return redirect("accounts:staff_list")

    return render(request, "accounts/staff_confirm_delete.html", {"staff": staff})


# =====================================================================
# Manager-initiated password reset
# =====================================================================
@owner_required
@require_POST
def staff_reset_password(request, pk):
    staff = get_object_or_404(User, pk=pk, business=request.user.business)

    if staff.pk == request.user.pk:
        messages.error(request, "Use 'Change password' in your profile.")
        return redirect("accounts:staff_list")

    temp_password = reset_user_password(staff, actor=request.user)

    request.session[SESSION_TEMP_PW_USER] = staff.pk
    request.session[SESSION_TEMP_PW_VALUE] = temp_password
    messages.success(
        request,
        f"Temporary password generated for {staff.username}. "
        f"It will only be shown once.",
    )
    return redirect("accounts:staff_list")


# =====================================================================
# Profile & password
# =====================================================================
@login_required
def profile(request):
    form = ProfileForm(
        request.POST or None, request.FILES or None, instance=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "form": form, "user_obj": request.user,
    })


@login_required
def password_change(request):
    form = CustomPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        mark_password_changed(user)
        messages.success(request, "Password updated successfully.")
        return redirect(post_login_redirect(user))
    return render(request, "accounts/password_change.html", {"form": form})


# =====================================================================
# Business settings (owner only)
# =====================================================================
@owner_required
def business_settings(request):
    business = request.user.business
    form = BusinessForm(
        request.POST or None, request.FILES or None, instance=business,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Business settings updated.")
        return redirect("accounts:business_settings")
    return render(request, "accounts/business_settings.html", {
        "form": form, "business": business,
    })


# =====================================================================
# Root dispatcher
# =====================================================================
@require_GET
def root_redirect(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    return redirect(post_login_redirect(request.user))