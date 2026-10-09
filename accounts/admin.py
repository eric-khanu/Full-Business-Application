from django.contrib import admin

# Register your models here.
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count

from .models import Business, User


# =====================================================================
# Business
# =====================================================================
@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "owner", "email",
        "currency", "is_active", "staff_count", "created_at",
    )
    list_filter = ("is_active", "currency")
    search_fields = ("name", "email", "phone1", "slug")
    readonly_fields = ("slug", "next_employee_number", "created_at", "updated_at")
    autocomplete_fields = ("owner",)
    ordering = ("name",)
    list_per_page = 50
    date_hierarchy = "created_at"
    save_on_top = True

    fieldsets = (
        (None, {"fields": ("name", "slug", "owner", "is_active")}),
        ("Contact", {
            "fields": ("address", "phone1", "phone2", "email", "logo"),
        }),
        ("Preferences", {"fields": ("tax_rate", "currency")}),
        ("Internal", {"fields": ("next_employee_number",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("owner")
            .annotate(_staff_count=Count("users"))
        )

    @admin.display(description="Staff", ordering="_staff_count")
    def staff_count(self, obj):
        return obj._staff_count


# =====================================================================
# User
# =====================================================================
@admin.register(User)
class CustomUserAdmin(DjangoUserAdmin):
    list_display = (
        "username", "full_name", "business", "role",
        "is_active_staff", "is_active", "is_staff", "must_change_password",
    )
    list_filter = (
        "role",
        ("business", admin.RelatedOnlyFieldListFilter),
        "is_active_staff",
        "is_active",
        "is_staff",
        "must_change_password",
    )
    search_fields = (
        "username", "first_name", "last_name",
        "email", "employee_id",
    )
    list_select_related = ("business",)
    autocomplete_fields = ("business",)
    ordering = ("business", "first_name", "last_name", "username")
    list_per_page = 50
    save_on_top = True

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Business & Role", {
            "fields": ("business", "role", "employee_id",
                       "is_active_staff", "hired_at"),
        }),
        ("Contact", {
            "fields": ("address", "phone1", "phone2", "profile_picture"),
        }),
        ("Password reset", {
            "fields": ("must_change_password",
                       "password_reset_by", "password_reset_at"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Business & Role", {
            "fields": ("business", "role", "is_active_staff", "employee_id"),
        }),
    )

    @admin.display(description="Name", ordering=("first_name", "last_name"))
    def full_name(self, obj):
        return obj.get_full_name() or obj.username

    # ---- Flag sync ----
    def save_model(self, request, obj, form, change):
        # Keep Django's login gate in sync with is_active_staff
        if "is_active_staff" in form.changed_data or not change:
            obj.is_active = obj.is_active_staff
        super().save_model(request, obj, form, change)

    # ---- Protect the sole owner ----
    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_owner and obj.business_id:
            # With OneToOneField owner, any owner is the "last" one
            messages.error(
                request,
                "Cannot delete a business owner. Transfer ownership first.",
            )
            return False
        return super().has_delete_permission(request, obj)