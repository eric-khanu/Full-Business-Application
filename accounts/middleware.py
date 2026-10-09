"""Request-level guards for the accounts app."""
import logging

from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)


class RequireBusinessMiddleware:
    """Every authenticated non-exempt request must belong to a business."""

    EXEMPT_PREFIXES = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/setup/",
        "/accounts/password/",
        "/admin/",
        "/static/",
        "/media/",
        "/api/",
        "/favicon.ico",
        "/robots.txt",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            request.business = None
            return self.get_response(request)

        request.business = user.business if user.business_id else None

        if self._is_exempt(request.path):
            return self.get_response(request)

        # Superusers without a business are platform admins — allow.
        if user.is_superuser and not user.business_id:
            return self.get_response(request)

        if not user.business_id:
            logger.warning(
                "Orphan user hit protected path",
                extra={"user_id": user.pk, "path": request.path},
            )
            logout(request)
            if self._wants_json(request):
                return JsonResponse(
                    {"detail": "Your account is not linked to a business."},
                    status=403,
                )
            return self._redirect_to_login(request)

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.EXEMPT_PREFIXES)

    @staticmethod
    def _wants_json(request) -> bool:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return True
        accept = request.headers.get("accept", "")
        return "application/json" in accept and "text/html" not in accept

    @staticmethod
    def _redirect_to_login(request):
        try:
            login_url = reverse("accounts:login")
        except NoReverseMatch:
            login_url = "/accounts/login/"
        return redirect(f"{login_url}?next={request.get_full_path()}")

# accounts/middleware.py
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse


class ForcePasswordChangeMiddleware:
    """Redirect to password-change until user.must_change_password is cleared."""

    # URL *names* — resolved once at startup, so they always match your
    # actual routing. If you move URLs around, this keeps working.
    ALLOWED_URL_NAMES = (
        "accounts:password_change",
        "accounts:login",
        "accounts:logout",
        "accounts:setup_owner",
    )

    # Path prefixes that are always exempt
    ALLOWED_PREFIXES = (
        "/admin/",
        "/static/",
        "/media/",
        "/api/",
        "/favicon.ico",
    )

    def __init__(self, get_response):
        self.get_response = get_response

        # Resolve URL names to actual paths once, at startup.
        self.allowed_paths = []
        for name in self.ALLOWED_URL_NAMES:
            try:
                self.allowed_paths.append(reverse(name))
            except NoReverseMatch:
                # If a URL doesn't exist yet, skip it silently.
                pass

    def __call__(self, request):
        user = getattr(request, "user", None)

        if (
            user
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
        ):
            path = request.path

            # Allow the change-password page itself and its siblings.
            if path in self.allowed_paths:
                return self.get_response(request)

            # Allow static/admin/api prefixes.
            if any(path.startswith(p) for p in self.ALLOWED_PREFIXES):
                return self.get_response(request)

            messages.warning(
                request, "You must change your password before continuing."
            )
            return redirect("accounts:password_change")

        return self.get_response(request)