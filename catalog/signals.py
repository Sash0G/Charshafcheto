from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import Product, WishlistItem


@receiver(user_logged_in)
def merge_guest_wishlist(sender, request, user, **kwargs):
    ids = request.session.pop("wishlist", None)
    if ids:
        for product in Product.objects.filter(pk__in=ids):
            WishlistItem.objects.get_or_create(user=user, product=product)
