from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Product, ProductVariant, Supplier
from core.models import SiteSettings
from orders import services
from orders.models import Coupon, Order, ShippingMethod


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", STRIPE_SECRET_KEY="")
class StoreTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        SiteSettings.load().save()
        cat = Category.objects.create(name="Спални комплекти")
        cls.supplier = Supplier.objects.create(name="Доставчик", email="sup@example.com")
        cls.product = Product.objects.create(name="Комплект „Зорница“", category=cat, price=Decimal("30.00"),
                                             cost_price=Decimal("12.00"), supplier=cls.supplier)
        cls.variant = ProductVariant.objects.create(product=cls.product, name="200 × 230", stock=5)
        cls.office = ShippingMethod.objects.create(name="Speedy офис", carrier="Speedy", price=Decimal("3.50"))

    def setUp(self):
        cache.clear()  # rate-limit counters

    def add(self, qty=1, variant=None):
        return self.client.post(reverse("cart:add"), {"variant": (variant or self.variant).pk, "quantity": qty})

    def checkout(self, **overrides):
        data = {"full_name": "Иван Иванов", "email": "ivan@example.com", "phone": "0888 123 456",
                "shipping_method": self.office.pk, "city": "София", "address": "Офис Лозенец",
                "payment_method": "cod", "accept_terms": "on", **overrides}
        return self.client.post(reverse("orders:checkout"), data)


class CartTests(StoreTestCase):
    def test_add_caps_quantity_at_stock(self):
        self.add(10)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 5)

    def test_out_of_stock_variant_is_rejected(self):
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=0)
        r = self.client.post(reverse("cart:add"), {"variant": self.variant.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 409)

    def test_inactive_product_disappears_from_cart(self):
        self.add()
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        r = self.client.get(reverse("cart:detail"))
        self.assertContains(r, "Количката е празна")

    def test_untracked_inventory_allows_ordering(self):
        Product.objects.filter(pk=self.product.pk).update(track_inventory=False)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=0)
        self.add(3)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 3)


class CheckoutTests(StoreTestCase):
    def test_guest_checkout_creates_order_and_decrements_stock(self):
        self.add(2)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.checkout()
        order = Order.objects.get()
        self.assertRedirects(r, reverse("orders:success", args=[order.token]))
        self.assertEqual(order.subtotal, Decimal("60.00"))
        self.assertEqual(order.shipping_total, Decimal("0.00"))  # over the 50 € free-shipping threshold
        self.assertEqual(order.cost_total, Decimal("24.00"))
        self.assertEqual(order.items.get().supplier, self.supplier)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 3)
        self.assertNotIn(str(self.variant.pk), self.client.session.get("cart", {}))
        self.assertEqual(len(mail.outbox), 2)  # customer + store

    def test_shipping_charged_below_threshold(self):
        self.add(1)
        self.checkout()
        self.assertEqual(Order.objects.get().total, Decimal("33.50"))

    def test_cannot_oversell(self):
        self.add(5)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=2)
        r = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(r, reverse("cart:detail"))
        self.assertFalse(Order.objects.exists())

    def test_terms_required(self):
        self.add()
        r = self.checkout(accept_terms="")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_invoice_fields_required_when_requested(self):
        self.add()
        r = self.checkout(needs_invoice="on")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_card_payment_hidden_without_stripe(self):
        self.add()
        self.checkout(payment_method="card")
        self.assertFalse(Order.objects.exists())

    def test_cancel_restores_stock(self):
        self.add(2)
        self.checkout()
        order = Order.objects.get()
        self.client.post(reverse("orders:cancel", args=[order.token]))
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertEqual(self.variant.stock, 5)

    def test_customer_cannot_cancel_shipped_order(self):
        self.add()
        self.checkout()
        order = Order.objects.get()
        services.change_status(order, Order.STATUS_SHIPPED, notify=False)
        self.client.post(reverse("orders:cancel", args=[order.token]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_SHIPPED)

    def test_track_order_requires_matching_email(self):
        self.add()
        self.checkout()
        order = Order.objects.get()
        r = self.client.post(reverse("orders:track"), {"number": order.number, "email": "other@example.com"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("orders:track"), {"number": order.number, "email": "IVAN@example.com"})
        self.assertRedirects(r, order.get_absolute_url())


class CouponTests(StoreTestCase):
    def test_percent_coupon(self):
        Coupon.objects.create(code="TEN", value=10)
        self.add()
        self.client.post(reverse("cart:coupon"), {"code": "ten"})
        self.checkout()
        order = Order.objects.get()
        self.assertEqual(order.discount_total, Decimal("3.00"))
        self.assertEqual(order.total, Decimal("30.50"))
        self.assertEqual(Coupon.objects.get().times_used, 1)

    def test_expired_coupon_rejected(self):
        Coupon.objects.create(code="OLD", value=10, valid_until=timezone.now() - timedelta(days=1))
        self.add()
        self.client.post(reverse("cart:coupon"), {"code": "OLD"})
        self.assertNotIn("cart_coupon", self.client.session)

    def test_free_shipping_coupon(self):
        Coupon.objects.create(code="SHIP", discount_type=Coupon.TYPE_FREE_SHIPPING)
        self.add()
        self.client.post(reverse("cart:coupon"), {"code": "SHIP"})
        self.checkout()
        self.assertEqual(Order.objects.get().shipping_total, Decimal("0.00"))

    def test_first_order_only(self):
        coupon = Coupon.objects.create(code="FIRST", value=10, first_order_only=True)
        self.add()
        self.checkout()
        self.assertEqual(coupon.check_valid(Decimal("100"), "ivan@example.com"), "Промо кодът важи само за първа поръчка.")


class DropshipTests(StoreTestCase):
    def test_confirming_forwards_to_auto_suppliers(self):
        Supplier.objects.filter(pk=self.supplier.pk).update(auto_forward=True)
        self.add()
        self.checkout()
        order = Order.objects.get()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.change_status(order, Order.STATUS_CONFIRMED, notify=False)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_SENT_TO_SUPPLIER)
        self.assertEqual(mail.outbox[0].to, ["sup@example.com"])
        self.assertEqual(order.supplier_orders.get().cost_total, Decimal("12.00"))


class WebhookTests(StoreTestCase):
    @override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x")
    def test_webhook_rejects_bad_signature(self):
        r = self.client.post(reverse("orders:stripe_webhook"), b"{}", content_type="application/json",
                             HTTP_STRIPE_SIGNATURE="t=1,v1=bad")
        self.assertEqual(r.status_code, 400)

    def test_mark_paid_moves_pending_order_to_new(self):
        self.add()
        with override_settings(STRIPE_SECRET_KEY="sk_test_x"):
            self.checkout(payment_method="card")
        order = Order.objects.get()
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(len(mail.outbox), 0)
        services.mark_paid(order, "pi_123")
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), (Order.STATUS_NEW, Order.PAY_PAID))
        self.assertEqual(len(mail.outbox), 2)


class AccountTests(StoreTestCase):
    def test_guest_orders_linked_only_after_email_verification(self):
        self.add()
        self.checkout()
        self.client.post(reverse("accounts:register"), {
            "first_name": "Иван", "email": "ivan@example.com", "password1": "Sl0zhna-Parola", "password2": "Sl0zhna-Parola",
            "accept_terms": "on",
        })
        user = User.objects.get(email="ivan@example.com")
        self.assertIsNone(Order.objects.get().user)
        link = next(m for m in mail.outbox if "Потвърдете" in m.subject).body.split("Потвърдете имейла си: ")[1].split()[0]
        self.client.get(link)
        self.assertEqual(Order.objects.get().user, user)

    def test_login_lockout(self):
        User.objects.create_user("a@example.com", "right-password-1")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "a@example.com", "password": "wrong"})
        r = self.client.post(reverse("accounts:login"), {"username": "a@example.com", "password": "right-password-1"})
        self.assertContains(r, "Твърде много неуспешни опити")

    def test_order_detail_requires_token(self):
        r = self.client.get("/checkout/order/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(r.status_code, 404)

    def test_open_redirect_blocked_on_register(self):
        r = self.client.post(reverse("accounts:register") + "?next=https://evil.example", {
            "first_name": "Ана", "email": "ana@example.com", "password1": "Sl0zhna-Parola", "password2": "Sl0zhna-Parola",
            "accept_terms": "on",
        })
        self.assertEqual(r["Location"], reverse("accounts:dashboard"))

    def test_delete_account_keeps_orders(self):
        user = User.objects.create_user("b@example.com", "pass-word-123")
        self.client.force_login(user)
        self.add()
        self.checkout(email="b@example.com")
        self.client.post(reverse("accounts:delete"), {"password": "pass-word-123"})
        self.assertFalse(User.objects.filter(email="b@example.com").exists())
        self.assertIsNone(Order.objects.get().user)
