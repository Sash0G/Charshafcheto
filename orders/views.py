import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from cart.cart import Cart
from core.models import SiteSettings

from . import services
from .forms import CheckoutForm
from .models import Order, ShippingMethod

log = logging.getLogger(__name__)


def _initial_for(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    initial = {"full_name": user.get_full_name(), "email": user.email, "phone": user.phone}
    address = user.addresses.first()
    if address:
        initial.update(full_name=address.full_name, phone=address.phone, city=address.city,
                       postcode=address.postcode, address=address.line1)
    return initial


def checkout(request):
    cart = Cart(request)
    if cart.is_empty:
        messages.info(request, "Количката ви е празна.")
        return redirect("cart:detail")
    if cart.stock_problems():
        messages.error(request, "Някои продукти в количката не са налични в желаното количество.")
        return redirect("cart:detail")

    form = CheckoutForm(request.POST or None, initial=_initial_for(request))
    methods = list(ShippingMethod.objects.filter(is_active=True))
    if not methods:
        messages.error(request, "В момента не приемаме поръчки. Моля, опитайте по-късно.")
        return redirect("cart:detail")

    selected = methods[0]
    if form.is_bound and form.data.get("shipping_method"):
        selected = next((m for m in methods if str(m.pk) == form.data["shipping_method"]), selected)
    email = form.data.get("email") if form.is_bound else (request.user.email if request.user.is_authenticated else None)
    totals = cart.totals(selected, email=email)
    base = totals.total - totals.shipping
    store = SiteSettings.load()

    if request.method == "POST" and form.is_valid():
        try:
            order = services.place_order(request, cart, form.cleaned_data, form.cleaned_data["shipping_method"])
        except services.CheckoutError as exc:
            messages.error(request, str(exc))
        else:
            cart.clear()
            request.session["last_order"] = str(order.token)
            if order.payment_method == Order.PAYMENT_CARD:
                return redirect("orders:pay", token=order.token)
            return redirect("orders:success", token=order.token)

    free_coupon = bool(totals.coupon and totals.coupon.discount_type == totals.coupon.TYPE_FREE_SHIPPING)
    shipping_costs = {m.pk: 0 if free_coupon else m.cost_for(base, store.free_shipping_threshold) for m in methods}
    return render(request, "orders/checkout.html", {
        "form": form,
        "totals": totals,
        "base_total": base,
        "shipping_options": [
            (m, shipping_costs[m.pk], str(m.pk) == str(form["shipping_method"].value() or methods[0].pk)) for m in methods
        ],
        "payment_help": CheckoutForm.PAYMENT_HELP,
        "coupon_next": "checkout",
    })


def _order_for(token):
    return get_object_or_404(Order.objects.prefetch_related("items__product__images"), token=token)


def success(request, token):
    order = _order_for(token)
    session_id = request.GET.get("session_id")
    if session_id and order.payment_status != Order.PAY_PAID and session_id == order.stripe_session_id:
        _sync_stripe_session(order, session_id)
        order.refresh_from_db()
    return render(request, "orders/success.html", {"order": order})


def detail(request, token):
    order = _order_for(token)
    return render(request, "orders/detail.html", {
        "order": order,
        "events": order.events.filter(is_public=True),
    })


def receipt(request, token):
    return render(request, "orders/receipt.html", {"order": _order_for(token)})


@require_POST
def cancel(request, token):
    order = _order_for(token)
    if order.is_cancellable_by_customer:
        services.change_status(order, Order.STATUS_CANCELLED, note="Отказана от клиента.")
        messages.success(request, f"Поръчка {order.number} е отказана.")
    else:
        messages.error(request, "Поръчката вече се обработва и не може да бъде отказана онлайн. Свържете се с нас.")
    return redirect("orders:detail", token=order.token)


class TrackForm(forms.Form):
    number = forms.CharField(label="Номер на поръчка", max_length=20)
    email = forms.EmailField(label="Имейл")


def track(request):
    form = TrackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from core.views import rate_limited

        if rate_limited(request, "track", 20):
            messages.error(request, "Твърде много опити. Опитайте отново по-късно.")
        else:
            order = Order.objects.filter(
                number__iexact=form.cleaned_data["number"].strip(), email__iexact=form.cleaned_data["email"]
            ).first()
            if order:
                return redirect("orders:detail", token=order.token)
            messages.error(request, "Не намерихме поръчка с тези данни.")
    return render(request, "orders/track.html", {"form": form})


# --------------------------------------------------------------------------
# Stripe card payments
# --------------------------------------------------------------------------
def _stripe():
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def pay(request, token):
    """Create (or reuse) a Stripe Checkout session and redirect to it."""
    order = _order_for(token)
    if order.payment_status == Order.PAY_PAID:
        return redirect("orders:success", token=order.token)
    if order.status != Order.STATUS_PENDING_PAYMENT or not settings.STRIPE_SECRET_KEY:
        raise Http404
    if request.GET.get("cancelled"):
        return render(request, "orders/pay_cancelled.html", {"order": order})

    stripe = _stripe()
    base = settings.SITE_URL
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=order.email,
            client_reference_id=str(order.token),
            metadata={"order_number": order.number, "order_token": str(order.token)},
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": order.currency.lower(),
                    "unit_amount": int((order.total * 100).to_integral_value()),
                    "product_data": {"name": f"Поръчка {order.number} — {SiteSettings.load().store_name}"},
                },
            }],
            success_url=base + reverse("orders:success", args=[order.token]) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + reverse("orders:pay", args=[order.token]) + "?cancelled=1",
            locale="bg",
        )
    except Exception:
        log.exception("Stripe session creation failed for %s", order.number)
        messages.error(request, "Плащането с карта временно не е достъпно. Опитайте отново или изберете друг метод.")
        return render(request, "orders/pay_cancelled.html", {"order": order})
    order.stripe_session_id = session.id
    order.save(update_fields=["stripe_session_id"])
    return redirect(session.url, permanent=False)


def _sync_stripe_session(order, session_id):
    try:
        session = _stripe().checkout.Session.retrieve(session_id)
    except Exception:
        log.exception("Could not retrieve Stripe session %s", session_id)
        return
    if session.payment_status == "paid":
        services.mark_paid(order, payment_intent=session.payment_intent or "")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponseBadRequest("Webhook not configured")
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid signature")

    obj = event["data"]["object"]
    order = Order.objects.filter(token=obj.get("client_reference_id") or "00000000-0000-0000-0000-000000000000").first() \
        if event["type"].startswith("checkout.session") else None
    if order is None:
        return HttpResponse(status=200)
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") == "paid":
            services.mark_paid(order, payment_intent=obj.get("payment_intent") or "")
    elif event["type"] in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        services.cancel_unpaid(order)
    return HttpResponse(status=200)
