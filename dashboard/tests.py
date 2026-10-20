from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from catalog.models import Category, Product, ProductVariant, Review, Supplier
from core.models import AuditLog, ContactMessage, SiteSettings
from orders.models import Coupon, Order, OrderItem, ShippingMethod, SupplierOrder

LIST_PAGES = [
    "home", "orders", "products", "product_create", "product_import", "categories", "categories_create",
    "suppliers", "suppliers_create", "coupons", "coupons_create", "shipping", "shipping_create",
    "pages", "pages_create", "customers", "reviews", "messages", "subscribers", "audit",
]
SUPERUSER_PAGES = ["settings", "team"]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DashboardTestBase(TestCase):
    def setUp(self):
        patcher = mock.patch("orders.services.send_templated_email", return_value=True)
        self.mail = patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("boss@example.com", "x-Strong-pass-1")
        cls.staff = User.objects.create_user("staff@example.com", "x-Strong-pass-1", is_staff=True)
        cls.customer = User.objects.create_user("client@example.com", "x-Strong-pass-1", first_name="Мария")
        cls.supplier = Supplier.objects.create(name="Текстил ООД", email="sup@example.com")
        cls.category = Category.objects.create(name="Чаршафи")
        cls.product = Product.objects.create(
            name="Чаршаф Тест", category=cls.category, supplier=cls.supplier,
            price=Decimal("20.00"), cost_price=Decimal("8.00"),
        )
        cls.variant = ProductVariant.objects.create(product=cls.product, name="220 × 240", sku="T-1", stock=10)
        cls.shipping = ShippingMethod.objects.create(name="Speedy офис", carrier="Speedy", price=Decimal("3.50"))
        cls.order = Order.objects.create(
            user=cls.customer, email=cls.customer.email, phone="0888", full_name="Мария Петрова",
            shipping_method=cls.shipping, shipping_method_name=cls.shipping.name, delivery_type="office",
            city="София", address="Офис Център", payment_method=Order.PAYMENT_COD,
            subtotal=Decimal("40.00"), shipping_total=Decimal("3.50"), total=Decimal("43.50"), cost_total=Decimal("16.00"),
        )
        OrderItem.objects.create(
            order=cls.order, product=cls.product, variant=cls.variant, supplier=cls.supplier,
            product_name=cls.product.name, variant_name=cls.variant.name, unit_price=Decimal("20.00"),
            unit_cost=Decimal("8.00"), quantity=2,
        )
        ProductVariant.objects.filter(pk=cls.variant.pk).update(stock=8)  # stock already taken by the order


class AccessControlTests(DashboardTestBase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertIn("next=", response["Location"])

    def test_customer_forbidden(self):
        self.client.force_login(self.customer)
        for name in LIST_PAGES:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 403, name)

    def test_staff_sees_every_list_page(self):
        self.client.force_login(self.staff)
        for name in LIST_PAGES:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 200, name)
        for url in [
            reverse("dashboard:order_detail", args=[self.order.pk]),
            reverse("dashboard:order_print", args=[self.order.pk]),
            reverse("dashboard:product_edit", args=[self.product.pk]),
            reverse("dashboard:supplier_detail", args=[self.supplier.pk]),
            reverse("dashboard:customer_detail", args=[self.customer.pk]),
            reverse("dashboard:customers") + "?tab=guests",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_settings_and_team_require_superuser(self):
        self.client.force_login(self.staff)
        for name in SUPERUSER_PAGES:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 403)
        self.client.force_login(self.admin)
        for name in SUPERUSER_PAGES:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 200)

    def test_mutations_require_post(self):
        self.client.force_login(self.staff)
        url = reverse("dashboard:order_status", args=[self.order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)


class OrderManagementTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_cancel_restocks_and_logs(self):
        response = self.client.post(
            reverse("dashboard:order_status", args=[self.order.pk]),
            {"status": Order.STATUS_CANCELLED, "note": "по желание на клиента", "notify": "on"},
        )
        self.assertRedirects(response, reverse("dashboard:order_detail", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)
        self.assertEqual(self.variant.stock, 10)
        self.assertTrue(AuditLog.objects.filter(action="status", object_id=str(self.order.pk)).exists())

    def test_tracking_marks_shipped(self):
        self.client.post(
            reverse("dashboard:order_tracking", args=[self.order.pk]),
            {"carrier": "Speedy", "tracking_number": "620001", "mark_shipped": "on"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.tracking_number, "620001")
        self.assertEqual(self.order.status, Order.STATUS_SHIPPED)
        self.assertIn("speedy.bg", self.order.tracking_url)

    def test_mark_paid(self):
        self.client.post(reverse("dashboard:order_payment", args=[self.order.pk]), {"action": "paid"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PAY_PAID)

    def test_forward_to_supplier(self):
        self.client.post(reverse("dashboard:order_forward", args=[self.order.pk]))
        so = SupplierOrder.objects.get(order=self.order)
        self.assertEqual(so.status, SupplierOrder.STATUS_SENT)
        self.assertEqual(so.cost_total, Decimal("16.00"))
        self.assertTrue(self.mail.called)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SENT_TO_SUPPLIER)

        response = self.client.post(
            reverse("dashboard:supplier_order_update", args=[self.order.pk, so.pk]),
            {f"so{so.pk}-status": "shipped", f"so{so.pk}-tracking_number": "X1",
             f"so{so.pk}-supplier_reference": "S-9", f"so{so.pk}-notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        so.refresh_from_db()
        self.assertEqual((so.status, so.tracking_number), ("shipped", "X1"))

    def test_csv_export(self):
        response = self.client.get(reverse("dashboard:orders_export") + "?status=new")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        body = response.content.decode("utf-8-sig")
        self.assertIn(self.order.number, body)
        self.assertIn("Мария Петрова", body)

    def test_list_filters(self):
        response = self.client.get(reverse("dashboard:orders"), {"q": "Мария", "status": "new"})
        self.assertContains(response, self.order.number)
        response = self.client.get(reverse("dashboard:orders"), {"status": "delivered"})
        self.assertNotContains(response, self.order.number)


def product_payload(**overrides):
    data = {
        "name": "Калъфка Нова", "slug": "", "sku": "", "category": "", "supplier": "", "supplier_url": "",
        "short_description": "", "description": "", "price": "12.90", "compare_at_price": "", "cost_price": "5.00",
        "material": "Памук", "pieces": "", "color": "", "care": "", "badge": "", "track_inventory": "on",
        "is_active": "on", "meta_title": "", "meta_description": "",
        "variants-TOTAL_FORMS": "2", "variants-INITIAL_FORMS": "0", "variants-MIN_NUM_FORMS": "1",
        "variants-MAX_NUM_FORMS": "1000",
        "variants-0-name": "50 × 70", "variants-0-sku": "K-1", "variants-0-stock": "5", "variants-0-is_active": "on",
        "variants-0-position": "0",
        "variants-1-name": "70 × 70", "variants-1-sku": "K-2", "variants-1-price_override": "14.90",
        "variants-1-stock": "3", "variants-1-is_active": "on", "variants-1-position": "1",
    }
    data.update(overrides)
    return data


class ProductManagementTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_create_product_with_variants(self):
        response = self.client.post(reverse("dashboard:product_create"), product_payload(category=self.category.pk))
        self.assertRedirects(response, reverse("dashboard:products"))
        product = Product.objects.get(name="Калъфка Нова")
        self.assertEqual(product.slug, "kalafka-nova")
        self.assertEqual(sorted(product.variants.values_list("sku", flat=True)), ["K-1", "K-2"])
        self.assertEqual(product.variants.get(sku="K-2").price, Decimal("14.90"))
        self.assertTrue(AuditLog.objects.filter(action="create", object_type="Product").exists())

    def test_product_requires_a_variant(self):
        payload = product_payload(category=self.category.pk, **{"variants-TOTAL_FORMS": "0"})
        response = self.client.post(reverse("dashboard:product_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(name="Калъфка Нова").exists())

    def test_image_upload_is_optimized(self):
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (2400, 1200), "red").save(buf, "JPEG")
        upload = SimpleUploadedFile("photo.jpg", buf.getvalue(), content_type="image/jpeg")
        payload = product_payload(category=self.category.pk, new_images=upload)
        with self.settings(MEDIA_ROOT=self._tmp_media()):
            self.client.post(reverse("dashboard:product_create"), payload)
            image = Product.objects.get(name="Калъфка Нова").images.get()
            self.assertTrue(image.image.name.endswith(".webp"))
            self.assertLessEqual(max(image.image.width, image.image.height), 1600)

    def _tmp_media(self):
        import tempfile

        path = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, path, True)
        return path

    def test_delete_product_with_orders_only_hides_it(self):
        self.client.post(reverse("dashboard:product_delete", args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_bulk_deactivate(self):
        self.client.post(reverse("dashboard:product_bulk"), {"ids": [self.product.pk], "action": "deactivate"})
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_duplicate(self):
        response = self.client.post(reverse("dashboard:product_duplicate", args=[self.product.pk]))
        copy = Product.objects.exclude(pk=self.product.pk).get()
        self.assertRedirects(response, reverse("dashboard:product_edit", args=[copy.pk]))
        self.assertFalse(copy.is_active)
        self.assertEqual(copy.variants.count(), 1)

    def test_csv_export_and_import_roundtrip(self):
        export = self.client.get(reverse("dashboard:product_export"))
        self.assertEqual(export["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("T-1", export.content.decode("utf-8-sig"))

        csv_text = (
            "sku,name,category,price,compare_at_price,cost_price,stock,supplier,variant\n"
            "T-1,Чаршаф Тест,Чаршафи,20.00,,8.00,25,Текстил ООД,220 × 240\n"
            "N-1,Завивка Облак,Завивки,40.90,,21.00,4,Текстил ООД,200 × 220\n"
            ",Без код,Завивки,1,,,1,,\n"
        )
        upload = SimpleUploadedFile("p.csv", csv_text.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse("dashboard:product_import"), {"file": upload})
        self.assertEqual(response.context["result"]["created"], 1)
        self.assertEqual(response.context["result"]["updated"], 1)
        self.assertEqual(len(response.context["result"]["errors"]), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 25)
        new = Product.objects.get(name="Завивка Облак")
        self.assertFalse(new.is_active)
        self.assertEqual(new.supplier, self.supplier)

    def test_category_with_products_cannot_be_deleted(self):
        response = self.client.post(reverse("dashboard:categories_delete", args=[self.category.pk]), follow=True)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertContains(response, "съдържа продукти")


class MiscSectionTests(DashboardTestBase):
    def test_coupon_create_uppercases_code(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("dashboard:coupons_create"), {
            "code": "spring15", "description": "", "discount_type": "percent", "value": "15",
            "min_order_total": "0", "valid_from": "", "valid_until": "", "usage_limit": "", "is_active": "on",
        })
        self.assertTrue(Coupon.objects.filter(code="SPRING15").exists())

    def test_review_approval_updates_rating(self):
        self.client.force_login(self.staff)
        review = Review.objects.create(product=self.product, name="Иван", rating=4, body="Добро")
        self.client.post(reverse("dashboard:review_action", args=[review.pk]), {"action": "approve"})
        self.product.refresh_from_db()
        self.assertEqual(self.product.rating_count, 1)
        self.assertEqual(self.product.rating_avg, Decimal("4.00"))

    def test_message_marked_read_when_opened(self):
        self.client.force_login(self.staff)
        msg = ContactMessage.objects.create(name="А", email="a@example.com", subject="Въпрос", message="Здравейте")
        self.client.get(reverse("dashboard:message_detail", args=[msg.pk]))
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)

    def test_settings_save(self):
        self.client.force_login(self.admin)
        current = SiteSettings.load()
        from django.forms.models import model_to_dict

        data = {k: v for k, v in model_to_dict(current).items() if v is not None and k != "id"}
        data.update(store_name="Чаршафчето БГ", free_shipping_threshold="60.00")
        data = {k: ("on" if v is True else v) for k, v in data.items() if v is not False}
        response = self.client.post(reverse("dashboard:settings"), data)
        self.assertRedirects(response, reverse("dashboard:settings"))
        self.assertEqual(SiteSettings.load().store_name, "Чаршафчето БГ")

    def test_team_create_and_self_demotion_blocked(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:team"), {
            "email": "new@example.com", "first_name": "Нов", "last_name": "", "phone": "", "password": "Very-Long-pass-77",
        })
        new = User.objects.get(email="new@example.com")
        self.assertTrue(new.is_staff)
        self.assertFalse(new.is_superuser)
        self.client.post(reverse("dashboard:team_toggle", args=[self.admin.pk]), {"action": "remove"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)

    def test_dashboard_kpis(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:home"), {"period": "7"})
        kpi = response.context["kpi"]
        self.assertEqual(kpi["revenue"], Decimal("43.50"))
        self.assertEqual(kpi["orders"], 1)
        self.assertEqual(kpi["profit"], Decimal("24.00"))
        self.assertTrue(response.context["chart"]["has_data"])
        self.assertContains(response, "<svg")

    def test_unsafe_next_is_ignored(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("dashboard:product_toggle", args=[self.product.pk]), {"next": "https://evil.example/"}
        )
        self.assertEqual(response["Location"], reverse("dashboard:products"))
