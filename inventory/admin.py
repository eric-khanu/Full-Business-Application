# inventory/admin.py
from django.contrib import admin
from django.db.models import Count

from .models import Category, Product, StockMovement, Supplier


# =====================================================================
# Category
# =====================================================================
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name", "business", "kind", "is_controlled",
        "product_count", "created_at",
    )
    list_filter = (
        ("business", admin.RelatedOnlyFieldListFilter),
        "kind",
        "is_controlled",
    )
    search_fields = ("name",)
    list_select_related = ("business",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("business")
            .annotate(_product_count=Count("products"))
        )

    @admin.display(description="Products", ordering="_product_count")
    def product_count(self, obj):
        return obj._product_count


# =====================================================================
# Supplier
# =====================================================================
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "name", "business", "phone", "email",
        "license_number", "is_active",
    )
    list_filter = (
        ("business", admin.RelatedOnlyFieldListFilter),
        "is_active",
    )
    search_fields = ("name", "phone", "email", "contact_person", "license_number")
    list_select_related = ("business",)
    readonly_fields = ("created_at", "updated_at")


# =====================================================================
# Product
# =====================================================================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "strength", "sku", "business",
        "category", "form", "quantity", "reorder_level",
        "selling_price", "is_prescription", "is_active",
    )
    list_filter = (
        ("business", admin.RelatedOnlyFieldListFilter),
        "category",
        "supplier",
        "form",
        "is_medicine",
        "is_prescription",
        "is_controlled",
        "is_active",
    )
    search_fields = ("name", "sku", "barcode", "strength")
    readonly_fields = ("sku", "barcode", "created_at", "updated_at")
    list_select_related = ("business", "category", "supplier")
    autocomplete_fields = ("category", "supplier")
    list_per_page = 50
    save_on_top = True
    date_hierarchy = "created_at"

    fieldsets = (
        ("Identity", {
            "fields": ("business", "sku", "barcode"),
            "description": "SKU and barcode are auto-generated on save.",
        }),
        ("Naming", {
            "fields": ("name", "strength", "form"),
        }),
        ("Classification", {
            "fields": ("category", "supplier", "is_medicine"),
        }),
        ("Pricing", {
            "fields": ("cost_price", "selling_price"),
        }),
        ("Pack", {
            "fields": ("pack_size", "unit"),
        }),
        ("Flags", {
            "fields": ("is_prescription", "is_controlled", "is_active"),
        }),
        ("Stock", {
            "fields": ("quantity", "reorder_level", "expiry_date"),
        }),
        ("Media", {
            "fields": ("image",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("business", "category", "supplier")
        )


# =====================================================================
# StockMovement (immutable audit log)
# =====================================================================
@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product", "movement_type", "quantity",
        "quantity_before", "quantity_after",
        "created_by", "created_at",
    )
    list_filter = (
        "movement_type",
        ("business", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("product__name", "product__sku", "reference", "reason")
    readonly_fields = (
        "business", "product", "movement_type",
        "quantity", "quantity_before", "quantity_after",
        "reason", "reference",
        "created_by", "created_at",
    )
    list_select_related = ("product", "created_by", "business")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False