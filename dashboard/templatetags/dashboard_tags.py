from django import template
from django.urls import NoReverseMatch, reverse

from catalog.models import Review
from core.models import ContactMessage
from orders.models import Order

register = template.Library()


@register.simple_tag
def dashboard_counts():
    return {
        "orders": Order.objects.filter(status=Order.STATUS_NEW).count(),
        "reviews": Review.objects.filter(is_approved=False).count(),
        "messages": ContactMessage.objects.filter(is_read=False).count(),
    }


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    """'active' when the current URL name starts with one of the prefixes."""
    match = getattr(context["request"], "resolver_match", None)
    name = match.url_name if match else ""
    return "active" if any(name == p or name.startswith(p + "_") for p in prefixes) else ""


@register.filter
def field_type(bound_field):
    return bound_field.field.widget.__class__.__name__


@register.simple_tag
def storefront_url(product):
    try:
        return reverse("catalog:product", args=[product.slug])
    except NoReverseMatch:
        return "#"
