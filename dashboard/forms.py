from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.forms import inlineformset_factory

from catalog.models import Category, Product, ProductVariant, Supplier
from core.models import Page, SiteSettings
from orders.models import Coupon, Order, ShippingMethod, SupplierOrder

User = get_user_model()

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(f, initial) for f in files]


class ProductForm(forms.ModelForm):
    new_images = MultipleImageField(
        label="Добави изображения", required=False,
        help_text="JPG, PNG или WebP. Големите снимки се оптимизират автоматично.",
    )

    class Meta:
        model = Product
        fields = [
            "name", "slug", "sku", "category", "supplier", "supplier_url",
            "short_description", "description",
            "price", "compare_at_price", "cost_price",
            "material", "pieces", "color", "care", "badge",
            "track_inventory", "is_active", "is_featured",
            "meta_title", "meta_description",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 7}),
            "short_description": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {"slug": "Оставете празно за автоматично генериране от името."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        for name in ("price", "cost_price", "compare_at_price"):
            self.fields[name].widget.attrs["data-margin"] = name

    def clean_sku(self):
        return self.cleaned_data.get("sku") or None

    def clean(self):
        data = super().clean()
        price, old = data.get("price"), data.get("compare_at_price")
        if price and old and old <= price:
            self.add_error("compare_at_price", "Старата цена трябва да е по-висока от текущата.")
        return data


VariantFormSet = inlineformset_factory(
    Product, ProductVariant,
    fields=["name", "sku", "supplier_sku", "price_override", "cost_override", "stock", "is_active", "position"],
    extra=0, min_num=1, validate_min=True, can_delete=True,
)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "slug", "parent", "tagline", "description", "image", "position", "is_active", "show_in_menu"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {"slug": "Оставете празно за автоматично генериране."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if self.instance.pk:
            self.fields["parent"].queryset = Category.objects.exclude(pk=self.instance.pk)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "email", "phone", "website", "processing_days", "auto_forward", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code", "description", "discount_type", "value", "min_order_total",
            "valid_from", "valid_until", "usage_limit", "once_per_customer", "first_order_only", "is_active",
        ]
        widgets = {"valid_from": DATETIME_WIDGET, "valid_until": DATETIME_WIDGET}

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if Coupon.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Вече съществува промо код с този код.")
        return code

    def clean(self):
        data = super().clean()
        if data.get("discount_type") == Coupon.TYPE_PERCENT and data.get("value") and data["value"] > 100:
            self.add_error("value", "Процентът не може да е над 100.")
        start, end = data.get("valid_from"), data.get("valid_until")
        if start and end and end <= start:
            self.add_error("valid_until", "Крайната дата трябва да е след началната.")
        return data


class ShippingMethodForm(forms.ModelForm):
    class Meta:
        model = ShippingMethod
        fields = ["name", "carrier", "delivery_type", "price", "free_shipping_eligible", "estimated_days", "position", "is_active"]


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ["title", "slug", "body", "show_in_footer", "order"]
        widgets = {"body": forms.Textarea(attrs={"rows": 14})}


class SiteSettingsForm(forms.ModelForm):
    FIELDSETS = [
        ("Магазин", ["store_name", "tagline", "announcement", "meta_description"]),
        ("Цени и наличност", ["currency", "show_secondary_currency", "free_shipping_threshold", "vat_rate",
                              "prices_include_vat", "low_stock_threshold"]),
        ("Контакти", ["contact_email", "orders_email", "contact_phone", "address", "facebook_url", "instagram_url"]),
        ("Фирма и фактуриране", ["company_name", "company_eik", "bank_name", "bank_iban"]),
    ]

    class Meta:
        model = SiteSettings
        exclude = ["updated_at"]

    def fieldsets(self):
        return [(title, [self[name] for name in names]) for title, names in self.FIELDSETS]


class StaffCreateForm(forms.ModelForm):
    password = forms.CharField(label="Парола", widget=forms.PasswordInput, strip=False)
    is_superuser = forms.BooleanField(label="Пълни права (настройки и екип)", required=False)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Потребител с този имейл вече съществува.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.is_staff = True
        user.is_superuser = self.cleaned_data["is_superuser"]
        if commit:
            user.save()
        return user


# ---- order detail forms ----------------------------------------------------
class OrderStatusForm(forms.Form):
    status = forms.ChoiceField(label="Нов статус", choices=Order.STATUS_CHOICES)
    note = forms.CharField(label="Бележка (вижда се от клиента)", required=False, max_length=300)
    notify = forms.BooleanField(label="Уведоми клиента по имейл", required=False, initial=True)


class TrackingForm(forms.ModelForm):
    mark_shipped = forms.BooleanField(label="Маркирай поръчката като изпратена", required=False, initial=True)

    class Meta:
        model = Order
        fields = ["carrier", "tracking_number"]


class NoteForm(forms.Form):
    message = forms.CharField(label="Вътрешна бележка", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class SupplierOrderForm(forms.ModelForm):
    class Meta:
        model = SupplierOrder
        fields = ["status", "supplier_reference", "tracking_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class CSVImportForm(forms.Form):
    file = forms.FileField(label="CSV файл", help_text="Колони: sku,name,category,price,compare_at_price,cost_price,stock,supplier,variant")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Моля, изберете .csv файл.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Файлът е твърде голям (макс. 5 MB).")
        return f
