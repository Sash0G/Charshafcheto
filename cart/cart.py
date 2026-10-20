"""Session-backed shopping cart.

Stored in the session as {"<variant_id>": qty}, so it works for guests and
survives login (Django keeps session data when an anonymous user logs in).
"""
from dataclasses import dataclass
from decimal import Decimal

from catalog.models import ProductVariant
from core.models import SiteSettings

SESSION_KEY = "cart"
COUPON_KEY = "cart_coupon"


@dataclass
class CartLine:
    variant: ProductVariant
    quantity: int

    @property
    def product(self):
        return self.variant.product

    @property
    def unit_price(self):
        return self.variant.price

    @property
    def line_total(self):
        return self.unit_price * self.quantity


@dataclass
class Totals:
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    total: Decimal
    coupon: object = None
    coupon_error: str = ""
    free_shipping_remaining: Decimal = Decimal("0")


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.data = self.session.get(SESSION_KEY) or {}
        self._lines = None

    # ---- mutation -----------------------------------------------------
    def _save(self):
        self.session[SESSION_KEY] = self.data
        self.session.modified = True
        self._lines = None

    def add(self, variant, quantity=1):
        key = str(variant.pk)
        new_qty = self.data.get(key, 0) + int(quantity)
        self.data[key] = max(1, min(new_qty, variant.max_quantity()))
        self._save()
        return self.data[key]

    def set(self, variant, quantity):
        key = str(variant.pk)
        quantity = int(quantity)
        if quantity <= 0:
            self.data.pop(key, None)
        else:
            self.data[key] = min(quantity, variant.max_quantity())
        self._save()

    def remove(self, variant_id):
        self.data.pop(str(variant_id), None)
        self._save()

    def clear(self):
        self.data = {}
        self.session.pop(COUPON_KEY, None)
        self._save()

    @property
    def coupon_code(self):
        return self.session.get(COUPON_KEY, "")

    def set_coupon(self, code):
        if code:
            self.session[COUPON_KEY] = code.strip().upper()
        else:
            self.session.pop(COUPON_KEY, None)
        self.session.modified = True

    # ---- reading ------------------------------------------------------
    def lines(self):
        if self._lines is None:
            ids = [int(k) for k in self.data if k.isdigit()]
            variants = (
                ProductVariant.objects.filter(pk__in=ids, is_active=True, product__is_active=True)
                .select_related("product", "product__category", "product__supplier")
                .prefetch_related("product__images")
            )
            by_id = {v.pk: v for v in variants}
            lines, dirty = [], False
            for key, qty in list(self.data.items()):
                variant = by_id.get(int(key)) if key.isdigit() else None
                if variant is None:
                    self.data.pop(key)
                    dirty = True
                    continue
                lines.append(CartLine(variant=variant, quantity=qty))
            if dirty:
                self._save()
            self._lines = lines
        return self._lines

    def __iter__(self):
        return iter(self.lines())

    def __len__(self):
        return sum(self.data.values())

    @property
    def count(self):
        return len(self)

    @property
    def is_empty(self):
        return not self.lines()

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines()), Decimal("0.00"))

    def stock_problems(self):
        """Lines whose requested quantity exceeds what's available now."""
        problems = []
        for line in self.lines():
            if not line.variant.available:
                problems.append((line, 0))
            elif line.product.track_inventory and line.quantity > line.variant.stock:
                problems.append((line, line.variant.stock))
        return problems

    def totals(self, shipping_method=None, email=None):
        from orders.models import Coupon

        settings = SiteSettings.load()
        subtotal = self.subtotal
        discount = Decimal("0.00")
        coupon, coupon_error = None, ""
        if self.coupon_code:
            coupon = Coupon.objects.filter(code=self.coupon_code).first()
            if coupon is None:
                coupon_error = "Невалиден промо код."
            else:
                coupon_error = coupon.check_valid(subtotal, email) or ""
                if coupon_error:
                    coupon = None
                else:
                    discount = coupon.discount_for(subtotal)

        shipping = Decimal("0.00")
        if shipping_method is not None:
            shipping = shipping_method.cost_for(subtotal - discount, settings.free_shipping_threshold)
            if coupon and coupon.discount_type == Coupon.TYPE_FREE_SHIPPING:
                shipping = Decimal("0.00")

        remaining = max(Decimal("0"), settings.free_shipping_threshold - (subtotal - discount))
        return Totals(
            subtotal=subtotal,
            discount=discount,
            shipping=shipping,
            total=max(Decimal("0.00"), subtotal - discount + shipping),
            coupon=coupon,
            coupon_error=coupon_error,
            free_shipping_remaining=remaining,
        )
