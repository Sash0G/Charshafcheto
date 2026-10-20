import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import F, Prefetch, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import Category, Product, ProductImage, ProductVariant, Supplier
from core.models import AuditLog, SiteSettings

from ..access import paginate, safe_next, staff_required
from ..forms import CSVImportForm, ProductForm, VariantFormSet

CSV_COLUMNS = ["sku", "name", "category", "price", "compare_at_price", "cost_price", "stock", "supplier", "variant"]


def filtered_products(request):
    qs = (
        Product.objects.select_related("category", "supplier")
        .prefetch_related("images", Prefetch("variants", queryset=ProductVariant.objects.order_by("position", "id")))
        .annotate(total_stock=Sum("variants__stock", filter=Q(variants__is_active=True)))
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(variants__sku__icontains=q)
                       | Q(variants__supplier_sku__icontains=q)).distinct()
    if request.GET.get("category"):
        qs = qs.filter(category_id=request.GET["category"])
    if request.GET.get("supplier"):
        qs = qs.filter(supplier_id=request.GET["supplier"])
    active = request.GET.get("active")
    if active in ("1", "0"):
        qs = qs.filter(is_active=active == "1")
    if request.GET.get("low"):
        threshold = SiteSettings.load().low_stock_threshold
        low_ids = ProductVariant.objects.filter(
            is_active=True, stock__lte=threshold, product__track_inventory=True
        ).values("product_id")
        qs = qs.filter(pk__in=low_ids)
    sort = request.GET.get("sort", "-created_at")
    if sort.lstrip("-") in ("name", "price", "created_at", "sales_count", "total_stock"):
        qs = qs.order_by(sort)
    return qs


@staff_required
def product_list(request):
    return render(request, "dashboard/products/list.html", {
        "page": paginate(request, filtered_products(request)),
        "categories": Category.objects.all(),
        "suppliers": Supplier.objects.all(),
        "low_threshold": SiteSettings.load().low_stock_threshold,
    })


def _save_images(request, product, form):
    for upload in form.cleaned_data.get("new_images") or []:
        position = (product.images.order_by("-position").values_list("position", flat=True).first() or 0) + 1
        ProductImage.objects.create(product=product, image=upload, alt=product.name, position=position)
    delete_ids = request.POST.getlist("delete_image")
    if delete_ids:
        product.images.filter(pk__in=delete_ids).delete()
    for image in product.images.all():
        raw = request.POST.get(f"image_position_{image.pk}")
        alt = request.POST.get(f"image_alt_{image.pk}")
        changed = []
        if raw is not None and raw.isdigit() and int(raw) != image.position:
            image.position = int(raw)
            changed.append("position")
        if alt is not None and alt != image.alt:
            image.alt = alt[:200]
            changed.append("alt")
        if changed:
            image.save(update_fields=changed)


def _product_form(request, product=None):
    is_new = product is None
    instance = product or Product()
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=instance)
        formset = VariantFormSet(request.POST, instance=instance, prefix="variants")
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                product = form.save()
                formset.instance = product
                formset.save()
                _save_images(request, product, form)
            AuditLog.record(request, "create" if is_new else "update", product)
            messages.success(request, "Продуктът е добавен." if is_new else "Продуктът е записан.")
            if "save_continue" in request.POST:
                return redirect("dashboard:product_edit", pk=product.pk)
            return redirect("dashboard:products")
        messages.error(request, "Моля, коригирайте грешките във формата.")
    else:
        initial = {}
        if is_new and request.GET.get("category"):
            initial["category"] = request.GET["category"]
        form = ProductForm(instance=instance, initial=initial)
        formset = VariantFormSet(
            instance=instance, prefix="variants",
            initial=[{"name": "Стандартен", "stock": 0, "is_active": True}] if is_new else None,
        )
        if is_new:
            formset.extra = 1
    return render(request, "dashboard/products/form.html", {
        "form": form, "formset": formset, "product": product, "is_new": is_new,
        "images": product.images.all() if product else [],
    })


@staff_required
def product_create(request):
    return _product_form(request)


@staff_required
def product_edit(request, pk):
    return _product_form(request, get_object_or_404(Product, pk=pk))


@staff_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    has_orders = product.order_items.exists()
    if request.method == "POST":
        if has_orders:
            product.is_active = False
            product.save(update_fields=["is_active", "updated_at"])
            AuditLog.record(request, "deactivate", product)
            messages.warning(request, "Продуктът има поръчки и затова е скрит от магазина вместо изтрит.")
        else:
            AuditLog.record(request, "delete", product)
            product.delete()
            messages.success(request, "Продуктът е изтрит.")
        return redirect("dashboard:products")
    return render(request, "dashboard/confirm_delete.html", {
        "object": product,
        "title": "Изтриване на продукт",
        "warning": "Този продукт фигурира в поръчки — ще бъде скрит от магазина, а не изтрит." if has_orders else "",
        "cancel_url": "dashboard:products",
    })


@staff_required
@require_POST
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active", "updated_at"])
    AuditLog.record(request, "activate" if product.is_active else "deactivate", product)
    messages.success(request, f"„{product.name}“ е {'публикуван' if product.is_active else 'скрит'}.")
    return redirect(safe_next(request, "dashboard:products"))


@staff_required
@require_POST
def product_duplicate(request, pk):
    original = get_object_or_404(Product.objects.prefetch_related("variants", "images"), pk=pk)
    with transaction.atomic():
        variants, images = list(original.variants.all()), list(original.images.all())
        copy = original
        copy.pk = None
        copy.name = f"{original.name} (копие)"
        copy.slug = ""
        copy.sku = None
        copy.is_active = False
        copy.sales_count = copy.rating_count = 0
        copy.rating_avg = 0
        copy.save()
        for v in variants:
            v.pk, v.product, v.sku = None, copy, ""
            v.save()
        for img in images:
            ProductImage.objects.create(product=copy, image=img.image.name, alt=img.alt, position=img.position)
    AuditLog.record(request, "create", copy, f"Копие на продукт: {copy.name}")
    messages.success(request, "Създадено е копие (скрито от магазина). Прегледайте го и го публикувайте.")
    return redirect("dashboard:product_edit", pk=copy.pk)


@staff_required
@require_POST
def product_bulk(request):
    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    qs = Product.objects.filter(pk__in=ids)
    if not ids or action not in ("activate", "deactivate", "delete"):
        messages.error(request, "Изберете продукти и действие.")
        return redirect("dashboard:products")
    if action in ("activate", "deactivate"):
        n = qs.update(is_active=action == "activate", updated_at=timezone.now())
        messages.success(request, f"Обновени продукти: {n}.")
    else:
        protected = qs.filter(order_items__isnull=False).distinct()
        hidden = protected.update(is_active=False)
        deletable = qs.exclude(pk__in=protected.values("pk"))
        n = deletable.count()
        deletable.delete()
        messages.success(request, f"Изтрити: {n}." + (f" Скрити (имат поръчки): {hidden}." if hidden else ""))
    AuditLog.record(request, f"bulk_{action}", None, f"Масово действие „{action}“ върху {len(ids)} продукта")
    return redirect("dashboard:products")


@staff_required
def product_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="products-{timezone.localdate():%Y%m%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(CSV_COLUMNS)
    for p in filtered_products(request):
        for v in p.variants.all():
            writer.writerow([
                v.sku or p.sku or "", p.name, p.category.name, v.price, p.compare_at_price or "",
                v.cost if v.cost is not None else "", v.stock, p.supplier.name if p.supplier else "", v.name,
            ])
    return response


def _dec(value, field, required=False):
    value = (value or "").strip().replace(",", ".")
    if not value:
        if required:
            raise ValueError(f"липсва {field}")
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError(f"невалидна стойност за {field}: {value}")


def import_rows(rows):
    """Create or update products/variants from CSV rows. Returns (created, updated, errors)."""
    created = updated = 0
    errors = []
    categories = {c.name.lower(): c for c in Category.objects.all()}
    suppliers = {s.name.lower(): s for s in Supplier.objects.all()}
    for line_no, row in enumerate(rows, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            sku = row.get("sku")
            if not sku:
                raise ValueError("липсва sku")
            price = _dec(row.get("price"), "price", required=True)
            old = _dec(row.get("compare_at_price"), "compare_at_price")
            cost = _dec(row.get("cost_price"), "cost_price")
            stock = int(row.get("stock") or 0)
            variant_name = row.get("variant") or "Стандартен"
            with transaction.atomic():
                variant = ProductVariant.objects.select_related("product").filter(sku=sku).first()
                if variant:
                    product = variant.product
                    if row.get("name"):
                        product.name = row["name"]
                    if old is not None:
                        product.compare_at_price = old
                    product.save()
                    variant.name = variant_name
                    variant.stock = stock
                    variant.price_override = None if price == product.price else price
                    variant.cost_override = None if cost is None or cost == product.cost_price else cost
                    variant.save()
                    updated += 1
                    continue
                cat_name = row.get("category")
                if not cat_name:
                    raise ValueError("липсва category")
                category = categories.get(cat_name.lower())
                if category is None:
                    category = Category.objects.create(name=cat_name, is_active=False)
                    categories[cat_name.lower()] = category
                supplier = suppliers.get(row.get("supplier", "").lower()) if row.get("supplier") else None
                name = row.get("name")
                if not name:
                    raise ValueError("липсва name")
                product = Product.objects.filter(name=name, category=category).first()
                if product is None:
                    product = Product.objects.create(
                        name=name, category=category, supplier=supplier, price=price,
                        compare_at_price=old, cost_price=cost, is_active=False,
                    )
                    created += 1
                else:
                    updated += 1
                ProductVariant.objects.create(
                    product=product, name=variant_name, sku=sku, stock=stock,
                    price_override=None if price == product.price else price,
                    cost_override=None if cost is None or cost == product.cost_price else cost,
                )
        except (ValueError, TypeError) as exc:
            errors.append(f"Ред {line_no}: {exc}")
    return created, updated, errors


@staff_required
def product_import(request):
    form = CSVImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        raw = form.cleaned_data["file"].read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1251", errors="replace")
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        missing = {"sku", "price"} - {(h or "").strip().lower() for h in reader.fieldnames or []}
        if missing:
            messages.error(request, f"Липсват задължителни колони: {', '.join(sorted(missing))}.")
        else:
            created, updated, errors = import_rows(reader)
            result = {"created": created, "updated": updated, "errors": errors}
            AuditLog.record(request, "import", None, f"CSV импорт: {created} нови, {updated} обновени, {len(errors)} грешки")
            if created or updated:
                messages.success(request, f"Импортът завърши: {created} нови и {updated} обновени. "
                                          "Новите продукти са скрити, докато не ги прегледате.")
    return render(request, "dashboard/products/import.html", {"form": form, "result": result, "columns": CSV_COLUMNS})


@staff_required
@require_POST
def variant_stock(request, pk):
    """Quick stock adjustment from the low-stock widget."""
    variant = get_object_or_404(ProductVariant, pk=pk)
    try:
        delta = int(request.POST.get("delta", "0"))
    except ValueError:
        delta = 0
    if delta:
        ProductVariant.objects.filter(pk=pk).update(stock=F("stock") + delta)
        variant.refresh_from_db()
        AuditLog.record(request, "stock", variant, f"{variant}: наличност {delta:+d} → {variant.stock}")
        messages.success(request, f"Наличността на „{variant}“ е {variant.stock} бр.")
    return redirect(safe_next(request, "dashboard:home"))
