"""Generic list / create / edit / delete views for the simpler entities."""
from django.contrib import messages
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from catalog.models import Category, Supplier
from core.models import AuditLog, Page
from orders.models import Coupon, ShippingMethod

from ..access import paginate, staff_required
from ..forms import CategoryForm, CouponForm, PageForm, ShippingMethodForm, SupplierForm


class Entity:
    def __init__(self, key, model, form, title, singular, search=(), annotate=None, order=None,
                 filters=None, delete_error=""):
        self.key = key
        self.model = model
        self.form = form
        self.title = title
        self.singular = singular
        self.search = search
        self.annotate = annotate or {}
        self.order = order
        self.filters = filters or {}
        self.delete_error = delete_error

    def queryset(self):
        qs = self.model.objects.all()
        if self.annotate:
            qs = qs.annotate(**self.annotate)
        if self.order:
            qs = qs.order_by(*self.order)
        return qs


ENTITIES = {
    "categories": Entity(
        "categories", Category, CategoryForm, "Категории", "категория",
        search=("name", "slug"), annotate={"n_products": Count("products")}, order=("position", "name"),
        filters={"active": "is_active"},
        delete_error="Категорията съдържа продукти. Преместете ги в друга категория или я скрийте.",
    ),
    "suppliers": Entity(
        "suppliers", Supplier, SupplierForm, "Доставчици", "доставчик",
        search=("name", "email", "contact_person"),
        annotate={"n_products": Count("products", distinct=True), "n_orders": Count("supplier_orders", distinct=True)},
        order=("name",), filters={"active": "is_active"},
        delete_error="Доставчикът има поръчки и не може да бъде изтрит. Деактивирайте го.",
    ),
    "coupons": Entity(
        "coupons", Coupon, CouponForm, "Промо кодове", "промо код",
        search=("code", "description"), order=("-created_at",), filters={"active": "is_active"},
    ),
    "shipping": Entity(
        "shipping", ShippingMethod, ShippingMethodForm, "Методи на доставка", "метод на доставка",
        search=("name", "carrier"), filters={"active": "is_active"},
        delete_error="Методът е използван в поръчки. Деактивирайте го вместо да го изтривате.",
    ),
    "pages": Entity("pages", Page, PageForm, "Страници", "страница", search=("title", "slug", "body")),
}


def _entity(key):
    entity = ENTITIES.get(key)
    if entity is None:
        from django.http import Http404

        raise Http404
    return entity


@staff_required
def entity_list(request, entity):
    e = _entity(entity)
    qs = e.queryset()
    q = request.GET.get("q", "").strip()
    if q and e.search:
        cond = Q()
        for field in e.search:
            cond |= Q(**{f"{field}__icontains": q})
        qs = qs.filter(cond)
    active = request.GET.get("active")
    if "active" in e.filters and active in ("1", "0"):
        qs = qs.filter(**{e.filters["active"]: active == "1"})
    return render(request, f"dashboard/{e.key}/list.html", {"e": e, "page": paginate(request, qs)})


@staff_required
def entity_form(request, entity, pk=None):
    e = _entity(entity)
    instance = get_object_or_404(e.model, pk=pk) if pk else None
    form = e.form(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST":
        if form.is_valid():
            obj = form.save()
            AuditLog.record(request, "update" if instance else "create", obj)
            messages.success(request, f"Записът „{obj}“ е запазен.")
            return redirect(f"dashboard:{e.key}")
        messages.error(request, "Моля, коригирайте грешките във формата.")
    return render(request, "dashboard/form.html", {
        "form": form,
        "title": f"Редакция: {instance}" if instance else f"Нов(а) {e.singular}",
        "back_url": reverse(f"dashboard:{e.key}"),
        "back_label": e.title,
        "object": instance,
        "delete_url": reverse(f"dashboard:{e.key}_delete", args=[instance.pk]) if instance else "",
    })


@staff_required
def entity_delete(request, entity, pk):
    e = _entity(entity)
    obj = get_object_or_404(e.model, pk=pk)
    if request.method == "POST":
        label = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, e.delete_error or "Записът се използва и не може да бъде изтрит.")
            return redirect(f"dashboard:{e.key}")
        AuditLog.objects.create(
            user=request.user, action="delete", object_type=e.model.__name__, object_id=str(pk), summary=label
        )
        messages.success(request, f"„{label}“ е изтрит(а).")
        return redirect(f"dashboard:{e.key}")
    return render(request, "dashboard/confirm_delete.html", {
        "object": obj, "title": f"Изтриване: {e.singular}", "cancel_url": f"dashboard:{e.key}",
    })


@staff_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    return render(request, "dashboard/suppliers/detail.html", {
        "supplier": supplier,
        "products": supplier.products.select_related("category").prefetch_related("images")[:50],
        "n_products": supplier.products.count(),
        "page": paginate(request, supplier.supplier_orders.select_related("order")),
    })
