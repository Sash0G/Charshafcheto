from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

from core.models import BGN_PER_EUR, SiteSettings

register = template.Library()


def _fmt(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _to_decimal(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


@register.filter
def money(value):
    """35.9 -> '35,90 €' using the store currency."""
    store = SiteSettings.load()
    return f"{_fmt(_to_decimal(value))} {store.currency_symbol}"


@register.filter
def money_alt(value):
    """Secondary currency for dual price display (EUR <-> BGN at the fixed rate)."""
    store = SiteSettings.load()
    if not store.show_secondary_currency:
        return ""
    value = _to_decimal(value)
    if store.currency == "EUR":
        return f"{_fmt(value * BGN_PER_EUR)} лв."
    return f"{_fmt(value / BGN_PER_EUR)} €"


@register.simple_tag
def price(value, css="price"):
    alt = money_alt(value)
    if alt:
        return format_html('<span class="{}">{}</span> <span class="price-alt">{}</span>', css, money(value), alt)
    return format_html('<span class="{}">{}</span>', css, money(value))


@register.filter
def stars(value):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = 0
    return "★" * n + "☆" * (5 - n)


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Rebuild the current querystring with some parameters replaced."""
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.filter
def status_class(status):
    return {
        "pending_payment": "pending",
        "new": "new",
        "confirmed": "processing",
        "sent_to_supplier": "processing",
        "shipped": "shipped",
        "delivered": "delivered",
        "cancelled": "cancelled",
        "returned": "cancelled",
        "unpaid": "pending",
        "paid": "delivered",
        "refunded": "cancelled",
        "failed": "cancelled",
        "pending": "new",
        "sent": "processing",
    }.get(status, "")
