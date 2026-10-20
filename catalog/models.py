from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Q, Sum
from django.urls import reverse

from core.utils import unique_slug


class Category(models.Model):
    name = models.CharField("име", max_length=100)
    slug = models.SlugField(unique=True, max_length=120, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children", verbose_name="родител"
    )
    tagline = models.CharField("подзаглавие", max_length=160, blank=True)
    description = models.TextField("описание", blank=True)
    image = models.ImageField("изображение", upload_to="categories/", blank=True)
    is_active = models.BooleanField("активна", default=True)
    show_in_menu = models.BooleanField("в главното меню", default=True)
    position = models.PositiveIntegerField("подредба", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "категория"
        verbose_name_plural = "категории"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])


class Supplier(models.Model):
    """Dropshipping supplier that fulfils orders on our behalf."""

    name = models.CharField("име", max_length=120)
    contact_person = models.CharField("лице за контакт", max_length=120, blank=True)
    email = models.EmailField("имейл за поръчки", blank=True)
    phone = models.CharField("телефон", max_length=40, blank=True)
    website = models.URLField("уебсайт", blank=True)
    processing_days = models.PositiveIntegerField(
        "срок за обработка (дни)", default=2, help_text="Колко работни дни отнема на доставчика да изпрати."
    )
    auto_forward = models.BooleanField(
        "автоматично препращане",
        default=False,
        help_text="Изпраща имейл с поръчката към доставчика веднага щом бъде потвърдена.",
    )
    notes = models.TextField("бележки", blank=True)
    is_active = models.BooleanField("активен", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "доставчик"
        verbose_name_plural = "доставчици"

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_stock(self):
        return self.annotate(
            total_stock=Sum("variants__stock", filter=Q(variants__is_active=True)),
        )


class Product(models.Model):
    name = models.CharField("име", max_length=200)
    slug = models.SlugField(unique=True, max_length=220, blank=True)
    sku = models.CharField("артикулен номер", max_length=60, unique=True, blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products", verbose_name="категория"
    )
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="products", verbose_name="доставчик"
    )
    supplier_url = models.URLField("линк към продукта при доставчика", blank=True)

    short_description = models.CharField("кратко описание", max_length=300, blank=True)
    description = models.TextField("описание", blank=True)

    price = models.DecimalField(
        "цена", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    compare_at_price = models.DecimalField(
        "стара цена", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Показва се зачеркната, когато продуктът е в промоция.",
    )
    cost_price = models.DecimalField(
        "доставна цена", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Цената, която плащате на доставчика. Използва се за изчисляване на печалбата.",
    )

    material = models.CharField("материя", max_length=120, blank=True)
    pieces = models.CharField("комплект", max_length=60, blank=True)
    color = models.CharField("цвят", max_length=80, blank=True)
    care = models.CharField("поддръжка", max_length=200, blank=True, default="Пране на 40°C, без белина")
    badge = models.CharField("етикет", max_length=30, blank=True, help_text="Напр. „Ново“ или „Най-продаван“.")

    track_inventory = models.BooleanField(
        "следи наличност",
        default=True,
        help_text="Изключете, ако наличността се управлява изцяло от доставчика.",
    )
    is_active = models.BooleanField("публикуван", default=True)
    is_featured = models.BooleanField("препоръчан на началната страница", default=False)

    meta_title = models.CharField("SEO заглавие", max_length=160, blank=True)
    meta_description = models.CharField("SEO описание", max_length=300, blank=True)

    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)
    search_text = models.TextField(editable=False, blank=True, help_text="Lower-cased text used for search.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "продукт"
        verbose_name_plural = "продукти"
        indexes = [models.Index(fields=["is_active", "category"]), models.Index(fields=["-sales_count"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if not self.sku:
            self.sku = None
        self.search_text = " ".join(
            filter(None, [self.name, self.sku, self.material, self.color, self.short_description,
                          self.category.name if self.category_id else ""])
        ).lower()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "search_text"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product", args=[self.slug])

    @property
    def main_image(self):
        images = list(self.images.all())
        return images[0] if images else None

    @property
    def on_sale(self):
        return bool(self.compare_at_price and self.compare_at_price > self.price)

    @property
    def discount_percent(self):
        if not self.on_sale:
            return 0
        return int(round((1 - self.price / self.compare_at_price) * 100))

    @property
    def margin(self):
        if self.cost_price is None:
            return None
        return self.price - self.cost_price

    def active_variants(self):
        return [v for v in self.variants.all() if v.is_active]

    @property
    def default_variant(self):
        variants = self.active_variants()
        return next((v for v in variants if v.available), variants[0] if variants else None)

    @property
    def has_options(self):
        return len(self.active_variants()) > 1

    @property
    def min_price(self):
        prices = [v.price for v in self.active_variants()]
        return min(prices) if prices else self.price

    @property
    def in_stock(self):
        return any(v.available for v in self.active_variants())

    @property
    def stock_total(self):
        return sum(v.stock for v in self.active_variants())

    def refresh_rating(self):
        agg = self.reviews.filter(is_approved=True).aggregate(avg=Avg("rating"), n=Count("id"))
        self.rating_avg = agg["avg"] or 0
        self.rating_count = agg["n"]
        self.save(update_fields=["rating_avg", "rating_count"])


IMAGE_MAX_SIDE = 1600


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField("изображение", upload_to="products/%Y/%m/")
    alt = models.CharField("алтернативен текст", max_length=200, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "изображение"
        verbose_name_plural = "изображения"

    def __str__(self):
        return self.alt or self.product.name

    def save(self, *args, **kwargs):
        if self.image and not self.pk and Path(self.image.name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            self._optimize()
        super().save(*args, **kwargs)

    def _optimize(self):
        """Downscale large uploads and store them as WebP to keep pages fast."""
        from PIL import Image, ImageOps

        try:
            img = Image.open(self.image)
            img = ImageOps.exif_transpose(img)
        except Exception:
            return
        img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=85, method=4)
        name = Path(self.image.name).with_suffix(".webp").name
        self.image.save(name, ContentFile(buf.getvalue()), save=False)


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField("вариант", max_length=100, help_text="Напр. размер „200 × 230 см“.")
    sku = models.CharField("артикулен номер", max_length=60, blank=True)
    supplier_sku = models.CharField("код при доставчика", max_length=80, blank=True)
    price_override = models.DecimalField(
        "цена (ако е различна)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    cost_override = models.DecimalField(
        "доставна цена (ако е различна)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    stock = models.IntegerField("наличност", default=0)
    is_active = models.BooleanField("активен", default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "вариант"
        verbose_name_plural = "варианти"

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    @property
    def price(self):
        return self.price_override if self.price_override is not None else self.product.price

    @property
    def cost(self):
        return self.cost_override if self.cost_override is not None else self.product.cost_price

    @property
    def available(self):
        return self.is_active and (not self.product.track_inventory or self.stock > 0)

    def max_quantity(self):
        if not self.product.track_inventory:
            return 99
        return max(0, min(self.stock, 99))


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="reviews")
    name = models.CharField("име", max_length=80)
    rating = models.PositiveSmallIntegerField(
        "оценка", validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField("заглавие", max_length=120, blank=True)
    body = models.TextField("отзив")
    is_verified = models.BooleanField("потвърдена покупка", default=False)
    is_approved = models.BooleanField("одобрен", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "отзив"
        verbose_name_plural = "отзиви"
        constraints = [
            models.UniqueConstraint(fields=["product", "user"], name="one_review_per_user_product"),
        ]

    def __str__(self):
        return f"{self.product} — {self.rating}★"


class WishlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="unique_wishlist_item")]
