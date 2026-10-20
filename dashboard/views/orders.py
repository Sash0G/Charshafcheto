import csv
from datetime import datetime

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import AuditLog, SiteSettings
from orders import services
from orders.models import Order, OrderEvent, SupplierOrder

from ..access import paginate, staff_required
from ..forms import NoteForm, OrderStatusForm, SupplierOrderForm, TrackingForm


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def filtered_orders(request):
    qs = Order.objects.select_related("user")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    payment = request.GET.get("payment", "")
    if payment:
        qs = qs.filter(payment_status=payment)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(number__icontains=q) | Q(full_name__icontains=q) | Q(email__icontains=q)
            | Q(phone__icontains=q) | Q(tracking_number__icontains=q)
        )
    date_from, date_to = _parse_date(request.GET.get("from")), _parse_date(request.GET.get("to"))
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


@staff_required
def order_list(request):
    qs = filtered_orders(request)
    counts = dict(Order.objects.values_list("status").annotate(n=Count("id")))
    tabs = [("", "Всички", sum(counts.values()))] + [
        (key, label, counts.get(key, 0)) for key, label in Order.STATUS_CHOICES
    ]
    return render(request, "dashboard/orders/list.html", {
        "page": paginate(request, qs),
        "tabs": tabs,
        "status": request.GET.get("status", ""),
        "payment_choices": Order.PAYMENT_STATUS_CHOICES,
    })


@staff_required
def order_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="orders-{timezone.localdate():%Y%m%d}.csv"'
    response.write("﻿")  # BOM so Excel opens Cyrillic correctly
    writer = csv.writer(response)
    writer.writerow([
        "Номер", "Дата", "Клиент", "Имейл", "Телефон", "Статус", "Плащане", "Статус плащане", "Доставка", "Град",
        "Адрес", "Междинна сума", "Отстъпка", "Доставка (цена)", "Общо", "Доставна стойност", "Печалба",
        "Промо код", "Товарителница",
    ])
    for o in filtered_orders(request).iterator():
        writer.writerow([
            o.number, timezone.localtime(o.created_at).strftime("%d.%m.%Y %H:%M"), o.full_name, o.email, o.phone,
            o.get_status_display(), o.get_payment_method_display(), o.get_payment_status_display(),
            o.shipping_method_name, o.city, o.address, o.subtotal, o.discount_total, o.shipping_total, o.total,
            o.cost_total, o.profit, o.coupon_code, o.tracking_number,
        ])
    return response


def _get_order(pk):
    return get_object_or_404(
        Order.objects.select_related("user", "coupon", "shipping_method").prefetch_related(
            "items__supplier", "items__variant", "items__product__images",
            "supplier_orders__supplier", "events__user",
        ),
        pk=pk,
    )


@staff_required
def order_detail(request, pk):
    order = _get_order(pk)
    has_supplier_items = any(item.supplier_id for item in order.items.all())
    return render(request, "dashboard/orders/detail.html", {
        "order": order,
        "status_form": OrderStatusForm(initial={"status": order.status, "notify": True}),
        "tracking_form": TrackingForm(instance=order, initial={
            "mark_shipped": order.status not in (Order.STATUS_SHIPPED, Order.STATUS_DELIVERED)
        }),
        "note_form": NoteForm(),
        "supplier_orders": [(so, SupplierOrderForm(instance=so, prefix=f"so{so.pk}")) for so in order.supplier_orders.all()],
        "has_supplier_items": has_supplier_items,
        "unassigned_items": [i for i in order.items.all() if not i.supplier_id],
        "open_statuses": [Order.STATUS_NEW, Order.STATUS_CONFIRMED, Order.STATUS_SENT_TO_SUPPLIER],
    })


@staff_required
@require_POST
def order_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = OrderStatusForm(request.POST)
    if form.is_valid():
        old = order.get_status_display()
        changed = services.change_status(
            order, form.cleaned_data["status"], user=request.user,
            note=form.cleaned_data["note"], notify=form.cleaned_data["notify"],
        )
        if changed:
            AuditLog.record(request, "status", order, f"{order.number}: {old} → {order.get_status_display()}")
            messages.success(request, f"Статусът е променен на „{order.get_status_display()}“.")
        else:
            messages.info(request, "Статусът не е променен.")
    else:
        messages.error(request, "Невалиден статус.")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
@require_POST
def order_payment(request, pk):
    order = get_object_or_404(Order, pk=pk)
    action = request.POST.get("action")
    if action == "paid":
        services.mark_paid(order, user=request.user)
        messages.success(request, "Поръчката е маркирана като платена.")
    elif action == "refunded" and order.payment_status == Order.PAY_PAID:
        order.payment_status = Order.PAY_REFUNDED
        order.save(update_fields=["payment_status", "updated_at"])
        OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_PAYMENT, user=request.user,
                                  message="Сумата е възстановена на клиента.", is_public=True)
        messages.success(request, "Плащането е маркирано като възстановено.")
    else:
        messages.error(request, "Действието не е позволено.")
        return redirect("dashboard:order_detail", pk=pk)
    AuditLog.record(request, "payment", order, f"{order.number}: плащане → {order.get_payment_status_display()}")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
@require_POST
def order_tracking(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = TrackingForm(request.POST, instance=order)
    if form.is_valid():
        form.save()
        OrderEvent.objects.create(
            order=order, kind=OrderEvent.KIND_NOTE, user=request.user,
            message=f"Товарителница: {order.carrier} {order.tracking_number}".strip(),
        )
        if (form.cleaned_data["mark_shipped"] and order.tracking_number
                and order.status not in (Order.STATUS_SHIPPED, Order.STATUS_DELIVERED, Order.STATUS_CANCELLED)):
            services.change_status(order, Order.STATUS_SHIPPED, user=request.user)
        AuditLog.record(request, "tracking", order, f"{order.number}: товарителница {order.tracking_number}")
        messages.success(request, "Данните за пратката са записани.")
    else:
        messages.error(request, "Проверете въведените данни за пратката.")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
@require_POST
def order_note(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_NOTE, user=request.user,
                                  message=form.cleaned_data["message"])
        messages.success(request, "Бележката е добавена.")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
@require_POST
def order_forward(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.POST.get("action") == "build":
        created = services.build_supplier_orders(order)
        messages.success(request, f"Подготвени поръчки към доставчици: {len(created)}.")
    else:
        sent = services.forward_to_suppliers(order, user=request.user)
        if sent:
            AuditLog.record(request, "forward", order, f"{order.number}: препратена към {sent} доставчик(а)")
            messages.success(request, f"Поръчката е препратена към {sent} доставчик(а).")
        else:
            messages.warning(request, "Няма чакащи поръчки към доставчици с имейл за изпращане.")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
@require_POST
def supplier_order_update(request, pk, so_pk):
    so = get_object_or_404(SupplierOrder, pk=so_pk, order_id=pk)
    form = SupplierOrderForm(request.POST, instance=so, prefix=f"so{so.pk}")
    if form.is_valid():
        so = form.save()
        OrderEvent.objects.create(
            order=so.order, kind=OrderEvent.KIND_SUPPLIER, user=request.user,
            message=f"{so.supplier.name}: {so.get_status_display()}"
                    + (f", товарителница {so.tracking_number}" if so.tracking_number else ""),
        )
        AuditLog.record(request, "update", so, f"{so.order.number} / {so.supplier.name}: {so.get_status_display()}")
        messages.success(request, f"Поръчката към {so.supplier.name} е обновена.")
    else:
        messages.error(request, "Проверете данните за поръчката към доставчика.")
    return redirect("dashboard:order_detail", pk=pk)


@staff_required
def order_print(request, pk):
    return render(request, "dashboard/orders/print.html", {
        "order": _get_order(pk),
        "store": SiteSettings.load(),
        "doc": "slip" if request.GET.get("doc") == "slip" else "invoice",
    })
