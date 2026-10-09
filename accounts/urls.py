from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Root
    path("", views.root_redirect, name="root"),

    # One-time bootstrap
    path("setup/", views.setup_owner, name="setup_owner"),

    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Staff
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_create, name="staff_create"),
    path("staff/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<int:pk>/toggle/", views.staff_toggle_active, name="staff_toggle"),
    path("staff/<int:pk>/delete/", views.staff_delete, name="staff_delete"),
    path(
        "staff/<int:pk>/reset-password/",
        views.staff_reset_password,
        name="staff_reset_password",
    ),

    # Profile & password
    path("profile/", views.profile, name="profile"),
    path("password/change/", views.password_change, name="password_change"),

    # Business
    path("business/", views.business_settings, name="business_settings"),
]