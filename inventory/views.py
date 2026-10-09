# inventory/views.py
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import manager_required, salesperson_required

from .barcode import barcode_data_uri     # ← was: from .barcode import barcode_svg


from .forms import CategoryForm, ProductForm, StockAdjustForm, SupplierForm
from .models import Category, Product, StockMovement, Supplier
from .services import (
    InsufficientStock,
    dispense_stock,
    dispose_expired,
    expired_products,
    expiring_products,
    low_stock_products,
    receive_stock,
    remove_stock,
    return_to_supplier,
    set_stock,
)


# =====================================================================
# Helpers
# =====================================================================
def _business(request):
    if not request.user.business:
        raise PermissionDenied("No business associated with this account.")
    return request.user.business


# =====================================================================
# Products
# =====================================================================
@salesperson_required
def product_list(request):
    b = _business(request)
    qs = (
        Product.objects
        .filter(business=b)
        .select_related("category", "supplier")
    )

    # Search — brand, SKU, barcode, strength
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(sku__icontains=q)
            | Q(barcode__icontains=q)
            | Q(strength__icontains=q)
        )

    # Category filter
    cat = request.GET.get("category")
    if cat:
        qs = qs.filter(category_id=cat)

    # Stock filters
    if request.GET.get("low_stock") == "1":
        qs = qs.filter(quantity__lte=F("reorder_level"))

    if request.GET.get("rx") == "1":
        qs = qs.filter(is_prescription=True)

    if request.GET.get("controlled") == "1":
        qs = qs.filter(is_controlled=True)

    if request.GET.get("expiring") == "1":
        from datetime import timedelta
        from django.utils import timezone
        cutoff = timezone.localdate() + timedelta(days=90)
        qs = qs.filter(
            expiry_date__isnull=False,
            expiry_date__lte=cutoff,
        )

    # Medicine vs non-medicine
    kind = request.GET.get("kind")
    if kind == "medicine":
        qs = qs.filter(is_medicine=True)
    elif kind == "other":
        qs = qs.filter(is_medicine=False)

    # Inactive
    if request.GET.get("inactive") != "1":
        qs = qs.filter(is_active=True)

    page = Paginator(qs.order_by("name"), 20).get_page(request.GET.get("page"))

    return render(request, "inventory/product_list.html", {
        "page": page,
        "q": q,
        "categories": b.categories.all().order_by("kind", "name"),
        "selected_category": cat,
        "low_stock_only": request.GET.get("low_stock") == "1",
        "rx_only": request.GET.get("rx") == "1",
        "controlled_only": request.GET.get("controlled") == "1",
        "expiring_only": request.GET.get("expiring") == "1",
        "kind_filter": kind,
        "show_inactive": request.GET.get("inactive") == "1",
        "can_manage": request.user.is_manager_or_above,
    })


@salesperson_required
def product_detail(request, pk):
    b = _business(request)
    product = get_object_or_404(Product, pk=pk, business=b)
    movements = (
        product.movements
        .select_related("created_by")
        .order_by("-created_at")[:20]
    )
    return render(request, "inventory/product_detail.html", {
        "product": product,
        "movements": movements,
        "barcode_image": barcode_data_uri(product.barcode) if product.barcode else "",
        "can_manage": request.user.is_manager_or_above,
        "show_costs": request.user.is_manager_or_above,
    })


@manager_required
def product_create(request):
    b = _business(request)
    form = ProductForm(
        request.POST or None, request.FILES or None, business=b,
    )
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.business = b

        # Stash the initial quantity; save with 0 and log it as a movement
        initial_qty = product.quantity or 0
        product.quantity = 0
        product.save()

        if initial_qty > 0:
            receive_stock(
                product=product,
                quantity=initial_qty,
                reason="Initial stock",
                actor=request.user,
            )

        messages.success(request, f'Product "{product.name}" created.')
        return redirect("inventory:product_detail", pk=product.pk)

    return render(request, "inventory/product_form.html", {
        "form": form,
        "title": "Add product",
    })


@manager_required
def product_edit(request, pk):
    b = _business(request)
    product = get_object_or_404(Product, pk=pk, business=b)
    form = ProductForm(
        request.POST or None, request.FILES or None,
        instance=product, business=b,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product updated.")
        return redirect("inventory:product_detail", pk=product.pk)

    return render(request, "inventory/product_form.html", {
        "form": form,
        "product": product,
        "title": f"Edit {product.name}",
    })


@manager_required
def product_delete(request, pk):
    b = _business(request)
    product = get_object_or_404(Product, pk=pk, business=b)

    if request.method == "POST":
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f'"{product.name}" has been deactivated.')
        return redirect("inventory:product_list")

    return render(request, "inventory/product_confirm_delete.html", {
        "product": product,
    })


@salesperson_required
def product_label(request, pk):
    """Printable barcode label for a product."""
    b = _business(request)
    product = get_object_or_404(Product, pk=pk, business=b)
    return render(request, "inventory/product_label.html", {
        "product": product,
        "barcode_image": barcode_data_uri(product.barcode) if product.barcode else "",
    })


# =====================================================================
# Stock
# =====================================================================
@manager_required
def stock_adjust(request, pk):
    b = _business(request)
    product = get_object_or_404(Product, pk=pk, business=b)
    form = StockAdjustForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        mode = form.cleaned_data["mode"]
        qty = form.cleaned_data["quantity"]
        reason = form.cleaned_data.get("reason", "")
        ref = form.cleaned_data.get("reference", "")

        try:
            if mode == StockMovement.MovementType.IN:
                receive_stock(product=product, quantity=qty, reason=reason, reference=ref, actor=request.user)
            elif mode == StockMovement.MovementType.OUT:
                dispense_stock(product=product, quantity=qty, reason=reason, reference=ref, actor=request.user)
            elif mode == StockMovement.MovementType.ADJUST:
                remove_stock(product=product, quantity=qty, reason=reason, reference=ref, actor=request.user)
            elif mode == StockMovement.MovementType.EXPIRED:
                dispose_expired(product=product, quantity=qty, reason=reason, reference=ref, actor=request.user)
            elif mode == StockMovement.MovementType.RETURN:
                return_to_supplier(product=product, quantity=qty, reason=reason, reference=ref, actor=request.user)
            else:  # "set"
                set_stock(product=product, new_quantity=qty, reason=reason, reference=ref, actor=request.user)
        except InsufficientStock as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Stock updated.")
            return redirect("inventory:product_detail", pk=product.pk)

    return render(request, "inventory/stock_adjust.html", {
        "product": product,
        "form": form,
    })


@salesperson_required
def stock_history(request):
    b = _business(request)
    qs = (
        StockMovement.objects
        .filter(business=b)
        .select_related("product", "created_by")
    )
    product_id = request.GET.get("product")
    if product_id:
        qs = qs.filter(product_id=product_id)

    mtype = request.GET.get("type")
    if mtype and mtype in StockMovement.MovementType.values:
        qs = qs.filter(movement_type=mtype)

    page = Paginator(qs, 30).get_page(request.GET.get("page"))

    return render(request, "inventory/stock_history.html", {
        "page": page,
        "products": b.products.filter(is_active=True).order_by("name"),
        "selected_product": product_id,
        "selected_type": mtype,
        "movement_types": StockMovement.MovementType.choices,
    })


@salesperson_required
def low_stock_list(request):
    b = _business(request)
    products = list(low_stock_products(b))
    for p in products:
        p.needed = max(p.reorder_level - p.quantity, 0)
    return render(request, "inventory/low_stock.html", {"products": products})


@salesperson_required
def expiring_list(request):
    """Products expiring within N days (default 90)."""
    b = _business(request)
    try:
        days = int(request.GET.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 365))
    products = list(expiring_products(b, days=days))
    return render(request, "inventory/expiring.html", {
        "products": products,
        "days": days,
    })


@salesperson_required
def expired_list(request):
    """Products already past expiry."""
    b = _business(request)
    products = list(expired_products(b))
    return render(request, "inventory/expired.html", {
        "products": products,
    })


# =====================================================================
# Categories
# =====================================================================
@manager_required
def category_list(request):
    b = _business(request)
    cats = (
        b.categories
        .annotate(product_count=Count("products"))
        .order_by("kind", "name")
    )
    return render(request, "inventory/category_list.html", {"categories": cats})


@manager_required
def category_create(request):
    b = _business(request)
    form = CategoryForm(request.POST or None, business=b)
    if request.method == "POST" and form.is_valid():
        cat = form.save(commit=False)
        cat.business = b
        cat.save()
        messages.success(request, "Category added.")
        return redirect("inventory:category_list")

    return render(request, "inventory/category_form.html", {
        "form": form,
        "title": "Add category",
    })


@manager_required
def category_edit(request, pk):
    b = _business(request)
    cat = get_object_or_404(Category, pk=pk, business=b)
    form = CategoryForm(request.POST or None, instance=cat, business=b)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category updated.")
        return redirect("inventory:category_list")

    return render(request, "inventory/category_form.html", {
        "form": form,
        "category": cat,
        "title": f"Edit {cat.name}",
    })


@manager_required
def category_delete(request, pk):
    b = _business(request)
    cat = get_object_or_404(Category, pk=pk, business=b)

    if request.method == "POST":
        cat.delete()   # Product.category = SET_NULL — safe
        messages.success(request, "Category deleted.")
        return redirect("inventory:category_list")

    return render(request, "inventory/category_confirm_delete.html", {
        "category": cat,
    })


# =====================================================================
# Suppliers
# =====================================================================
@manager_required
def supplier_list(request):
    b = _business(request)
    qs = b.suppliers.order_by("name")

    if request.GET.get("active"):
        qs = qs.filter(is_active=True)

    if request.GET.get("missing_licence"):
        # Match both NULL and empty string
        qs = qs.filter(Q(license_number="") | Q(license_number__isnull=True))

    return render(request, "inventory/supplier_list.html", {
        "suppliers": qs,
    })


@manager_required
def supplier_create(request):
    b = _business(request)
    form = SupplierForm(request.POST or None, business=b)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.business = b
        s.save()
        messages.success(request, "Supplier added.")
        return redirect("inventory:supplier_list")

    return render(request, "inventory/supplier_form.html", {
        "form": form,
        "title": "Add supplier",
    })


@manager_required
def supplier_edit(request, pk):
    b = _business(request)
    s = get_object_or_404(Supplier, pk=pk, business=b)
    form = SupplierForm(request.POST or None, instance=s, business=b)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier updated.")
        return redirect("inventory:supplier_list")

    return render(request, "inventory/supplier_form.html", {
        "form": form,
        "supplier": s,
        "title": f"Edit {s.name}",
    })