from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import models

BGN_PER_EUR = Decimal("1.95583")  # fixed conversion rate


class SiteSettings(models.Model):
    """Singleton with the store-wide configuration editable from the admin panel."""

    CURRENCY_CHOICES = [("EUR", "EUR (€)"), ("BGN", "BGN (лв.)")]

    store_name = models.CharField("име на магазина", max_length=80, default="Чаршафчето")
    tagline = models.CharField("слоган", max_length=160, default="Повече уют в живота")
    announcement = models.CharField(
        "лента с обява",
        max_length=200,
        blank=True,
        default="🚚 Безплатна доставка за поръчки над 50 € · 14 дни право на връщане",
    )
    currency = models.CharField("валута", max_length=3, choices=CURRENCY_CHOICES, default="EUR")
    show_secondary_currency = models.BooleanField(
        "показвай и цена в лева", default=True, help_text="Двойно обозначаване EUR / BGN по фиксирания курс."
    )
    free_shipping_threshold = models.DecimalField(
        "безплатна доставка над", max_digits=10, decimal_places=2, default=Decimal("50.00")
    )
    vat_rate = models.DecimalField("ДДС %", max_digits=5, decimal_places=2, default=Decimal("20.00"))
    prices_include_vat = models.BooleanField("цените са с ДДС", default=True)
    low_stock_threshold = models.PositiveIntegerField("праг за ниска наличност", default=5)

    contact_email = models.EmailField("имейл за контакт", default="info@charshafcheto.bg")
    orders_email = models.EmailField("имейл за известия за поръчки", default="orders@charshafcheto.bg")
    contact_phone = models.CharField("телефон", max_length=40, default="0888 123 456")
    address = models.CharField("адрес", max_length=200, default="България")

    company_name = models.CharField("фирма", max_length=120, blank=True)
    company_eik = models.CharField("ЕИК", max_length=20, blank=True)
    bank_iban = models.CharField("IBAN за банков превод", max_length=40, blank=True)
    bank_name = models.CharField("банка", max_length=80, blank=True)

    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)

    meta_description = models.CharField(
        "SEO описание",
        max_length=300,
        default="Спални комплекти, чаршафи, калъфки и завивки с български дух.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = "site_settings"

    class Meta:
        verbose_name = "настройки на магазина"
        verbose_name_plural = "настройки на магазина"

    def __str__(self):
        return self.store_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def load(cls):
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 300)
        return obj

    @property
    def currency_symbol(self):
        return "€" if self.currency == "EUR" else "лв."


class Page(models.Model):
    """Editable informational pages: delivery, returns, terms, privacy..."""

    title = models.CharField("заглавие", max_length=120)
    slug = models.SlugField(unique=True, allow_unicode=True)
    body = models.TextField("съдържание", help_text="Позволен е обикновен HTML.")
    show_in_footer = models.BooleanField("в долното меню", default=True)
    order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "страница"
        verbose_name_plural = "страници"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("core:page", args=[self.slug])


class ContactMessage(models.Model):
    name = models.CharField("име", max_length=120)
    email = models.EmailField("имейл")
    phone = models.CharField("телефон", max_length=32, blank=True)
    subject = models.CharField("тема", max_length=160)
    message = models.TextField("съобщение")
    is_read = models.BooleanField("прочетено", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "съобщение"
        verbose_name_plural = "съобщения"

    def __str__(self):
        return f"{self.name}: {self.subject}"


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "абонат"
        verbose_name_plural = "абонати"

    def __str__(self):
        return self.email


class AuditLog(models.Model):
    """Who changed what in the admin panel."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=40, blank=True)
    summary = models.CharField(max_length=300)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.user}: {self.summary}"

    @classmethod
    def record(cls, request, action, obj, summary=""):
        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
        return cls.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=action,
            object_type=obj.__class__.__name__ if obj is not None else "",
            object_id=str(getattr(obj, "pk", "") or ""),
            summary=(summary or str(obj))[:300],
            ip_address=ip or None,
        )
