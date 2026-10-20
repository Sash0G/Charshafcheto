import logging
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from catalog.models import Product, ProductVariant
from core.models import SiteSettings
from core.utils import client_ip

from .models import Coupon, Order, OrderEvent, OrderItem, SupplierOrder

log = logging.getLogger(__name__)


class CheckoutError(Exception):
    pass


# --------------------------------------------------------------------------
# Emails
# --------------------------------------------------------------------------
def send_templated_email(subject, template, context, to, reply_to=None):
    ctx = {"store": SiteSettings.load(), "site_url": settings.SITE_URL, **context}
    try:
        text = render_to_string(f"emails/{template}.txt", ctx)
        html = render_to_string(f"emails/{template}.html", ctx)
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, to, reply_to=reply_to)
        msg.attach_alternative(html, "text/html")
        msg.send()
        return True
    except Exception:  # never break checkout because the mail server is down
        log.exception("Failed to send email %s to %s", template, to)
        return False


def notify_customer(order, template, subject):
    if send_templated_email(subject, template, {"order": order}, [order.email]):
        OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_EMAIL, message=f"Изпратен имейл: {subject}")


def send_order_emails(order):
    store = SiteSettings.load()
    notify_customer(order, "order_confirmation", f"Поръчка {order.number} е приета — {store.store_name}")
    send_templated_email(
        f"Нова поръчка {order.number} ({order.total} {order.currency})",
        "order_admin_notification",
        {"order": order},
        [store.orders_email],
        reply_to=[order.email],
    )


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------
@transaction.atomic
def place_order(request, cart, data, shipping_method):
    """Create an order from the cart. Locks variants to prevent overselling."""
    store = SiteSettings.load()
    lines = cart.lines()
    if not lines:
        raise CheckoutError("Количката е празна.")

    variant_ids = [line.variant.pk for line in lines]
    locked = {
        v.pk: v
        for v in ProductVariant.objects.select_for_update()
        .select_related("product", "product__supplier")
        .filter(pk__in=variant_ids)
    }
    for line in lines:
        v = locked.get(line.variant.pk)
        if v is None or not v.available:
            raise CheckoutError(f"„{line.product.name}“ вече не е наличен.")
        if v.product.track_inventory and v.stock < line.quantity:
            raise CheckoutError(f"Наличността на „{v.product.name} — {v.name}“ е {v.stock} бр.")

    totals = cart.totals(shipping_method, email=data["email"])
    if cart.coupon_code and totals.coupon_error:
        raise CheckoutError(totals.coupon_error)

    is_card = data["payment_method"] == Order.PAYMENT_CARD
    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        email=data["email"].lower(),
        phone=data["phone"],
        full_name=data["full_name"],
        shipping_method=shipping_method,
        shipping_method_name=shipping_method.name,
        delivery_type=shipping_method.delivery_type,
        carrier=shipping_method.carrier,
        city=data["city"],
        postcode=data.get("postcode", ""),
        address=data["address"],
        payment_method=data["payment_method"],
        status=Order.STATUS_PENDING_PAYMENT if is_card else Order.STATUS_NEW,
        currency=store.currency,
        subtotal=totals.subtotal,
        discount_total=totals.discount,
        shipping_total=totals.shipping,
        total=totals.total,
        coupon=totals.coupon,
        coupon_code=totals.coupon.code if totals.coupon else "",
        needs_invoice=data.get("needs_invoice", False),
        company_name=data.get("company_name", ""),
        company_eik=data.get("company_eik", ""),
        company_vat=data.get("company_vat", ""),
        company_mol=data.get("company_mol", ""),
        company_address=data.get("company_address", ""),
        customer_note=data.get("customer_note", ""),
        ip_address=client_ip(request),
        accepted_terms_at=timezone.now(),
    )

    cost_total = Decimal("0.00")
    for line in lines:
        v = locked[line.variant.pk]
        unit_cost = v.cost or Decimal("0.00")
        cost_total += unit_cost * line.quantity
        OrderItem.objects.create(
            order=order,
            product=v.product,
            variant=v,
            supplier=v.product.supplier,
            product_name=v.product.name,
            variant_name=v.name,
            sku=v.sku or v.product.sku or "",
            supplier_sku=v.supplier_sku,
            unit_price=v.price,
            unit_cost=unit_cost,
            quantity=line.quantity,
        )
        if v.product.track_inventory:
            ProductVariant.objects.filter(pk=v.pk).update(stock=F("stock") - line.quantity)
        Product.objects.filter(pk=v.product_id).update(sales_count=F("sales_count") + line.quantity)

    order.cost_total = cost_total
    order.save(update_fields=["cost_total"])
    if totals.coupon:
        Coupon.objects.filter(pk=totals.coupon.pk).update(times_used=F("times_used") + 1)

    OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_STATUS, message="Поръчката е създадена.", is_public=True)

    # Remember the address for logged-in customers who don't have one yet.
    if request.user.is_authenticated and data.get("save_address") and shipping_method.delivery_type == "address":
        request.user.addresses.get_or_create(
            line1=data["address"], city=data["city"],
            defaults={"full_name": data["full_name"], "phone": data["phone"], "postcode": data.get("postcode", ""),
                      "is_default": not request.user.addresses.exists()},
        )

    if not is_card:
        transaction.on_commit(lambda: send_order_emails(order))
    return order


# --------------------------------------------------------------------------
# Status changes
# --------------------------------------------------------------------------
STATUS_EMAILS = {
    Order.STATUS_CONFIRMED: ("order_status", "Поръчка {number} е потвърдена"),
    Order.STATUS_SHIPPED: ("order_shipped", "Поръчка {number} е изпратена"),
    Order.STATUS_DELIVERED: ("order_status", "Поръчка {number} е доставена"),
    Order.STATUS_CANCELLED: ("order_status", "Поръчка {number} е отказана"),
    Order.STATUS_RETURNED: ("order_status", "Връщане по поръчка {number} е обработено"),
}


def restock(order):
    for item in order.items.select_related("variant__product"):
        if item.variant and item.variant.product.track_inventory:
            ProductVariant.objects.filter(pk=item.variant_id).update(stock=F("stock") + item.quantity)


@transaction.atomic
def change_status(order, new_status, user=None, note="", notify=True):
    old = order.status
    if new_status == old:
        return False
    order.status = new_status
    now = timezone.now()
    fields = ["status", "updated_at"]
    if new_status == Order.STATUS_SHIPPED and not order.shipped_at:
        order.shipped_at = now
        fields.append("shipped_at")
    if new_status == Order.STATUS_DELIVERED:
        order.delivered_at = now
        fields.append("delivered_at")
        if order.payment_method == Order.PAYMENT_COD and order.payment_status == Order.PAY_UNPAID:
            order.payment_status, order.paid_at = Order.PAY_PAID, now
            fields += ["payment_status", "paid_at"]
    order.save(update_fields=fields)

    released = {Order.STATUS_CANCELLED, Order.STATUS_RETURNED}
    if new_status in released and old not in released:
        restock(order)
        if order.coupon_id:
            Coupon.objects.filter(pk=order.coupon_id, times_used__gt=0).update(times_used=F("times_used") - 1)

    message = f"Статус: {order.get_status_display()}"
    if note:
        message += f" — {note}"
    OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_STATUS, message=message, user=user, is_public=True)

    if notify and new_status in STATUS_EMAILS:
        template, subject = STATUS_EMAILS[new_status]
        transaction.on_commit(lambda: notify_customer(order, template, subject.format(number=order.number)))

    if new_status == Order.STATUS_CONFIRMED:
        auto = [s for s in suppliers_for(order) if s.auto_forward and s.email]
        if auto:
            transaction.on_commit(lambda: forward_to_suppliers(order, user=user, only=auto))
    return True


def mark_paid(order, payment_intent="", user=None):
    if order.payment_status == Order.PAY_PAID:
        return
    order.payment_status = Order.PAY_PAID
    order.paid_at = timezone.now()
    if payment_intent:
        order.stripe_payment_intent = payment_intent
    order.save(update_fields=["payment_status", "paid_at", "stripe_payment_intent", "updated_at"])
    OrderEvent.objects.create(order=order, kind=OrderEvent.KIND_PAYMENT, message="Плащането е получено.", user=user, is_public=True)
    if order.status == Order.STATUS_PENDING_PAYMENT:
        order.status = Order.STATUS_NEW
        order.save(update_fields=["status"])
        send_order_emails(order)


@transaction.atomic
def cancel_unpaid(order, reason="Плащането не беше завършено."):
    if order.status == Order.STATUS_PENDING_PAYMENT:
        change_status(order, Order.STATUS_CANCELLED, note=reason, notify=False)


# --------------------------------------------------------------------------
# Dropshipping: forward order lines to the suppliers that fulfil them
# --------------------------------------------------------------------------
def suppliers_for(order):
    return {item.supplier for item in order.items.select_related("supplier") if item.supplier}


@transaction.atomic
def build_supplier_orders(order):
    """Group order items by supplier and create/refresh SupplierOrder rows."""
    grouped = defaultdict(list)
    for item in order.items.select_related("supplier"):
        if item.supplier:
            grouped[item.supplier].append(item)
    result = []
    for supplier, items in grouped.items():
        so, _ = SupplierOrder.objects.get_or_create(order=order, supplier=supplier)
        so.cost_total = sum((i.line_cost for i in items), Decimal("0.00"))
        so.save(update_fields=["cost_total", "updated_at"])
        OrderItem.objects.filter(pk__in=[i.pk for i in items]).update(supplier_order=so)
        result.append(so)
    return result


def forward_to_suppliers(order, user=None, only=None):
    """Email each supplier its part of the order. Returns number of emails sent."""
    sent = 0
    for so in build_supplier_orders(order):
        if only is not None and so.supplier not in only:
            continue
        if so.status not in (SupplierOrder.STATUS_PENDING,) or not so.supplier.email:
            continue
        ok = send_templated_email(
            f"Нова поръчка за изпълнение {order.number}",
            "supplier_order",
            {"order": order, "supplier_order": so, "items": so.items.all()},
            [so.supplier.email],
            reply_to=[SiteSettings.load().orders_email],
        )
        if ok:
            so.status, so.sent_at = SupplierOrder.STATUS_SENT, timezone.now()
            so.save(update_fields=["status", "sent_at", "updated_at"])
            OrderEvent.objects.create(
                order=order, kind=OrderEvent.KIND_SUPPLIER, user=user,
                message=f"Поръчката е препратена към {so.supplier.name} ({so.supplier.email}).",
            )
            sent += 1
    if sent and order.status in (Order.STATUS_NEW, Order.STATUS_CONFIRMED):
        order.status = Order.STATUS_SENT_TO_SUPPLIER
        order.save(update_fields=["status", "updated_at"])
    return sent
