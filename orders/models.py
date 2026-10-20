import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, ProductVariant, Supplier


class ShippingMethod(models.Model):
    TYPE_OFFICE = "office"
    TYPE_ADDRESS = "address"
    TYPE_CHOICES = [(TYPE_OFFICE, "До офис на куриер"), (TYPE_ADDRESS, "До адрес")]

    name = models.CharField("име", max_length=100)
    carrier = models.CharField("куриер", max_length=40, help_text="Напр. Speedy, Econt.")
    delivery_type = models.CharField("тип", max_length=10, choices=TYPE_CHOICES, default=TYPE_OFFICE)
    price = models.DecimalField("цена", max_digits=8, decimal_places=2)
    free_shipping_eligible = models.BooleanField(
        "участва в безплатната доставка", default=True,
        help_text="Безплатна при поръчка над прага от настройките.",
    )
    estimated_days = models.CharField("срок", max_length=40, default="2–4 работни дни")
    is_active = models.BooleanField("активен", default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "price"]
        verbose_name = "метод на доставка"
        verbose_name_plural = "методи на доставка"

    def __str__(self):
        return self.name

    def cost_for(self, subtotal, free_threshold):
        if self.free_shipping_eligible and free_threshold and subtotal >= free_threshold:
            return Decimal("0.00")
        return self.price


class Coupon(models.Model):
    TYPE_PERCENT = "percent"
    TYPE_FIXED = "fixed"
    TYPE_FREE_SHIPPING = "free_shipping"
    TYPE_CHOICES = [
        (TYPE_PERCENT, "Процент от сумата"),
        (TYPE_FIXED, "Фиксирана сума"),
        (TYPE_FREE_SHIPPING, "Безплатна доставка"),
    ]

    code = models.CharField("код", max_length=40, unique=True)
    description = models.CharField("описание", max_length=200, blank=True)
    discount_type = models.CharField("тип", max_length=20, choices=TYPE_CHOICES, default=TYPE_PERCENT)
    value = models.DecimalField("стойност", max_digits=8, decimal_places=2, default=0)
    min_order_total = models.DecimalField("минимална поръчка", max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField("валиден от", null=True, blank=True)
    valid_until = models.DateTimeField("валиден до", null=True, blank=True)
    usage_limit = models.PositiveIntegerField("общ лимит на използване", null=True, blank=True)
    once_per_customer = models.BooleanField("веднъж на клиент", default=False)
    first_order_only = models.BooleanField("само за първа поръчка", default=False)
    times_used = models.PositiveIntegerField("използван", default=0)
    is_active = models.BooleanField("активен", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "промо код"
        verbose_name_plural = "промо кодове"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def check_valid(self, subtotal, email=None):
        """Return an error message, or None when the coupon can be applied."""
        now = timezone.now()
        if not self.is_active:
            return "Промо кодът не е активен."
        if self.valid_from and now < self.valid_from:
            return "Промо кодът все още не е валиден."
        if self.valid_until and now > self.valid_until:
            return "Промо кодът е изтекъл."
        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return "Промо кодът е изчерпан."
        if subtotal < self.min_order_total:
            return f"Промо кодът важи за поръчки над {self.min_order_total:.2f}."
        if email:
            placed = Order.objects.filter(email__iexact=email).exclude(status=Order.STATUS_CANCELLED)
            if self.first_order_only and placed.exclude(status=Order.STATUS_PENDING_PAYMENT).exists():
                return "Промо кодът важи само за първа поръчка."
            if self.once_per_customer and placed.filter(coupon=self).exists():
                return "Вече сте използвали този промо код."
        return None

    def discount_for(self, subtotal):
        if self.discount_type == self.TYPE_PERCENT:
            return (subtotal * self.value / Decimal("100")).quantize(Decimal("0.01"))
        if self.discount_type == self.TYPE_FIXED:
            return min(self.value, subtotal)
        return Decimal("0.00")

    @property
    def label(self):
        if self.discount_type == self.TYPE_PERCENT:
            return f"-{self.value.normalize():f}%"
        if self.discount_type == self.TYPE_FIXED:
            return f"-{self.value:.2f}"
        return "Безплатна доставка"


class Order(models.Model):
    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_NEW = "new"
    STATUS_CONFIRMED = "confirmed"
    STATUS_SENT_TO_SUPPLIER = "sent_to_supplier"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"
    STATUS_RETURNED = "returned"
    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, "Очаква плащане"),
        (STATUS_NEW, "Нова"),
        (STATUS_CONFIRMED, "Потвърдена"),
        (STATUS_SENT_TO_SUPPLIER, "При доставчика"),
        (STATUS_SHIPPED, "Изпратена"),
        (STATUS_DELIVERED, "Доставена"),
        (STATUS_CANCELLED, "Отказана"),
        (STATUS_RETURNED, "Върната"),
    ]
    OPEN_STATUSES = [STATUS_NEW, STATUS_CONFIRMED, STATUS_SENT_TO_SUPPLIER, STATUS_SHIPPED]
    REVENUE_EXCLUDED = [STATUS_PENDING_PAYMENT, STATUS_CANCELLED, STATUS_RETURNED]

    PAYMENT_COD = "cod"
    PAYMENT_CARD = "card"
    PAYMENT_BANK = "bank"
    PAYMENT_CHOICES = [
        (PAYMENT_COD, "Наложен платеж"),
        (PAYMENT_CARD, "Карта"),
        (PAYMENT_BANK, "Банков превод"),
    ]

    PAY_UNPAID = "unpaid"
    PAY_PAID = "paid"
    PAY_REFUNDED = "refunded"
    PAY_FAILED = "failed"
    PAYMENT_STATUS_CHOICES = [
        (PAY_UNPAID, "Неплатена"),
        (PAY_PAID, "Платена"),
        (PAY_REFUNDED, "Възстановена"),
        (PAY_FAILED, "Неуспешно плащане"),
    ]

    number = models.CharField("номер", max_length=20, unique=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )

    email = models.EmailField("имейл")
    phone = models.CharField("телефон", max_length=32)
    full_name = models.CharField("име и фамилия", max_length=120)

    shipping_method = models.ForeignKey(ShippingMethod, null=True, on_delete=models.SET_NULL)
    shipping_method_name = models.CharField("доставка", max_length=120)
    delivery_type = models.CharField(max_length=10, choices=ShippingMethod.TYPE_CHOICES)
    city = models.CharField("град", max_length=80)
    postcode = models.CharField("пощенски код", max_length=12, blank=True)
    address = models.CharField("адрес / офис", max_length=255)

    payment_method = models.CharField("плащане", max_length=10, choices=PAYMENT_CHOICES)
    payment_status = models.CharField(
        "статус на плащането", max_length=10, choices=PAYMENT_STATUS_CHOICES, default=PAY_UNPAID
    )
    status = models.CharField("статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)

    currency = models.CharField(max_length=3, default="EUR")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    cost_total = models.DecimalField(
        "доставна стойност", max_digits=10, decimal_places=2, default=0,
        help_text="Сумата към доставчиците за продуктите в поръчката.",
    )

    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    coupon_code = models.CharField(max_length=40, blank=True)

    needs_invoice = models.BooleanField("желае фактура", default=False)
    company_name = models.CharField("фирма", max_length=160, blank=True)
    company_eik = models.CharField("ЕИК", max_length=20, blank=True)
    company_vat = models.CharField("ДДС номер", max_length=20, blank=True)
    company_mol = models.CharField("МОЛ", max_length=120, blank=True)
    company_address = models.CharField("адрес на регистрация", max_length=255, blank=True)

    customer_note = models.TextField("бележка от клиента", blank=True)
    carrier = models.CharField("куриер", max_length=40, blank=True)
    tracking_number = models.CharField("товарителница", max_length=80, blank=True)

    stripe_session_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent = models.CharField(max_length=255, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    accepted_terms_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "поръчка"
        verbose_name_plural = "поръчки"
        indexes = [models.Index(fields=["status", "-created_at"]), models.Index(fields=["email"])]

    def __str__(self):
        return self.number or f"Поръчка #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"CH-{100000 + self.pk}"
            Order.objects.filter(pk=self.pk).update(number=self.number)

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.token])

    @property
    def profit(self):
        return self.total - self.shipping_total - self.cost_total

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def tracking_url(self):
        if not self.tracking_number:
            return ""
        carrier = (self.carrier or self.shipping_method_name).lower()
        if "speedy" in carrier:
            return f"https://www.speedy.bg/bg/track-shipment?shipmentNumber={self.tracking_number}"
        if "econt" in carrier:
            return f"https://www.econt.com/services/track-shipment/{self.tracking_number}"
        return ""

    @property
    def is_cancellable_by_customer(self):
        return self.status in (self.STATUS_PENDING_PAYMENT, self.STATUS_NEW)

    @property
    def progress_step(self):
        """Index used by the customer-facing order timeline."""
        steps = [self.STATUS_NEW, self.STATUS_CONFIRMED, self.STATUS_SHIPPED, self.STATUS_DELIVERED]
        status = self.STATUS_CONFIRMED if self.status == self.STATUS_SENT_TO_SUPPLIER else self.status
        return steps.index(status) if status in steps else -1


class SupplierOrder(models.Model):
    """The part of a customer order forwarded to one dropshipping supplier."""

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_CONFIRMED = "confirmed"
    STATUS_SHIPPED = "shipped"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Чака изпращане"),
        (STATUS_SENT, "Изпратена към доставчика"),
        (STATUS_CONFIRMED, "Потвърдена от доставчика"),
        (STATUS_SHIPPED, "Изпратена от доставчика"),
        (STATUS_CANCELLED, "Отказана"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="supplier_orders")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="supplier_orders")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    supplier_reference = models.CharField("номер при доставчика", max_length=80, blank=True)
    tracking_number = models.CharField("товарителница", max_length=80, blank=True)
    cost_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["order", "supplier"], name="one_supplier_order_per_supplier")]

    def __str__(self):
        return f"{self.order.number} → {self.supplier}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL, related_name="order_items")
    variant = models.ForeignKey(ProductVariant, null=True, on_delete=models.SET_NULL, related_name="order_items")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    supplier_order = models.ForeignKey(
        SupplierOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="items"
    )
    product_name = models.CharField(max_length=200)
    variant_name = models.CharField(max_length=100, blank=True)
    sku = models.CharField(max_length=80, blank=True)
    supplier_sku = models.CharField(max_length=80, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def line_cost(self):
        return self.unit_cost * self.quantity


class OrderEvent(models.Model):
    """Timeline entry: status changes, notes, emails sent."""

    KIND_STATUS = "status"
    KIND_NOTE = "note"
    KIND_EMAIL = "email"
    KIND_PAYMENT = "payment"
    KIND_SUPPLIER = "supplier"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=10, default=KIND_NOTE)
    message = models.TextField()
    is_public = models.BooleanField(default=False, help_text="Видимо за клиента.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.message[:60]
