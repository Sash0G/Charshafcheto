from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from catalog.models import ProductVariant
from orders.models import Coupon, ShippingMethod

from .cart import Cart


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _qty(request, default=1):
    try:
        return max(0, min(int(request.POST.get("quantity", default)), 99))
    except (TypeError, ValueError):
        return default


def _cheapest_shipping():
    return ShippingMethod.objects.filter(is_active=True).order_by("price").first()


def _drawer_html(request, cart):
    return render_to_string("cart/_drawer.html", {"cart": cart, "totals": cart.totals()}, request=request)


def _respond(request, cart, message="", error=False, status=200):
    if _is_ajax(request):
        payload = {"cart_count": cart.count, "html": _drawer_html(request, cart)}
        payload["error" if error else "message"] = message
        return JsonResponse(payload, status=status)
    if message:
        (messages.error if error else messages.success)(request, message)
    return redirect("cart:detail")


def detail(request):
    cart = Cart(request)
    shipping = _cheapest_shipping()
    return render(request, "cart/detail.html", {
        "totals": cart.totals(shipping),
        "shipping_estimate": shipping,
        "stock_problems": cart.stock_problems(),
    })


def drawer(request):
    cart = Cart(request)
    return render(request, "cart/_drawer.html", {"cart": cart, "totals": cart.totals()})


@require_POST
def add(request):
    cart = Cart(request)
    variant = ProductVariant.objects.filter(
        pk=request.POST.get("variant") or 0, is_active=True, product__is_active=True
    ).select_related("product").first()
    if variant is None:
        return _respond(request, cart, "Моля, изберете вариант.", error=True, status=400)
    if not variant.available:
        return _respond(request, cart, "Този продукт е изчерпан.", error=True, status=409)
    before = cart.data.get(str(variant.pk), 0)
    after = cart.add(variant, _qty(request) or 1)
    if after == before:
        return _respond(request, cart, f"Наличността е ограничена до {variant.max_quantity()} бр.", error=True, status=409)
    return _respond(request, cart, "Добавено в количката")


@require_POST
def update(request, variant_id):
    cart = Cart(request)
    variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=variant_id)
    cart.set(variant, _qty(request))
    return _respond(request, cart)


@require_POST
def remove(request, variant_id):
    cart = Cart(request)
    cart.remove(variant_id)
    return _respond(request, cart, "Продуктът е премахнат")


@require_POST
def coupon(request):
    cart = Cart(request)
    if request.POST.get("remove"):
        cart.set_coupon("")
        messages.success(request, "Промо кодът е премахнат.")
    else:
        code = (request.POST.get("code") or "").strip().upper()
        found = Coupon.objects.filter(code=code).first() if code else None
        error = "Невалиден промо код." if found is None else found.check_valid(
            cart.subtotal, request.user.email if request.user.is_authenticated else None
        )
        if error:
            messages.error(request, error)
        else:
            cart.set_coupon(code)
            messages.success(request, f"Промо кодът {code} е приложен.")
    nxt = request.POST.get("next")
    return redirect("orders:checkout" if nxt == "checkout" else "cart:detail")
