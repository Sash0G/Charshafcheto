from django.conf import settings

from cart.cart import Cart
from catalog.models import Category, WishlistItem

from .models import Page, SiteSettings


def store(request):
    if request.path.startswith(("/static/", "/media/")):
        return {}
    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(WishlistItem.objects.filter(user=request.user).values_list("product_id", flat=True))
    else:
        wishlist_ids = set(request.session.get("wishlist", []))
    return {
        "store": SiteSettings.load(),
        "cart": Cart(request),
        "wishlist_ids": wishlist_ids,
        "menu_categories": Category.objects.filter(is_active=True, show_in_menu=True, parent__isnull=True),
        "footer_pages": Page.objects.filter(show_in_footer=True),
        "card_payments_enabled": bool(settings.STRIPE_SECRET_KEY),
        "SITE_URL": settings.SITE_URL,
    }
