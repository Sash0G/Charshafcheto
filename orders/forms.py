import re

from django import forms
from django.conf import settings

from .models import Order, ShippingMethod

PHONE_RE = re.compile(r"^\+?[\d\s\-()]{9,20}$")


class CheckoutForm(forms.Form):
    full_name = forms.CharField(label="Име и фамилия", max_length=120)
    email = forms.EmailField(label="Имейл")
    phone = forms.CharField(label="Телефон", max_length=32)
    shipping_method = forms.ModelChoiceField(
        label="Доставка", queryset=ShippingMethod.objects.none(), widget=forms.RadioSelect, empty_label=None
    )
    city = forms.CharField(label="Град / село", max_length=80)
    postcode = forms.CharField(label="Пощенски код", max_length=12, required=False)
    address = forms.CharField(label="Адрес / офис на куриер", max_length=255)
    payment_method = forms.ChoiceField(label="Плащане", widget=forms.RadioSelect)
    customer_note = forms.CharField(
        label="Бележка към поръчката", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3})
    )
    needs_invoice = forms.BooleanField(label="Желая фактура", required=False)
    company_name = forms.CharField(label="Фирма", max_length=160, required=False)
    company_eik = forms.CharField(label="ЕИК", max_length=20, required=False)
    company_vat = forms.CharField(label="ДДС номер", max_length=20, required=False)
    company_mol = forms.CharField(label="МОЛ", max_length=120, required=False)
    company_address = forms.CharField(label="Адрес на регистрация", max_length=255, required=False)
    save_address = forms.BooleanField(label="Запази адреса в профила ми", required=False, initial=True)
    accept_terms = forms.BooleanField(
        label="Прочетох и приемам общите условия и политиката за поверителност",
        error_messages={"required": "Трябва да приемете общите условия."},
    )

    PAYMENT_HELP = {
        Order.PAYMENT_COD: "Плащате на куриера при получаване.",
        Order.PAYMENT_CARD: "Visa, Mastercard, Apple Pay, Google Pay — защитено плащане чрез Stripe.",
        Order.PAYMENT_BANK: "Ще получите банковите данни по имейл. Изпращаме след получаване на плащането.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shipping_method"].queryset = ShippingMethod.objects.filter(is_active=True)
        choices = [(Order.PAYMENT_COD, "Наложен платеж")]
        if settings.STRIPE_SECRET_KEY:
            choices.append((Order.PAYMENT_CARD, "Плащане с карта"))
        from core.models import SiteSettings

        if SiteSettings.load().bank_iban:
            choices.append((Order.PAYMENT_BANK, "Банков превод"))
        self.fields["payment_method"].choices = choices
        self.fields["payment_method"].initial = Order.PAYMENT_COD
        autocomplete = {
            "full_name": "name", "email": "email", "phone": "tel", "city": "address-level2",
            "postcode": "postal-code", "address": "street-address",
        }
        self.fields["accept_terms"].widget.attrs["form"] = "checkoutForm"  # rendered outside the <form>
        for name, value in autocomplete.items():
            self.fields[name].widget.attrs["autocomplete"] = value

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Въведете валиден телефонен номер.")
        return phone

    def clean(self):
        data = super().clean()
        if data.get("needs_invoice"):
            for f in ("company_name", "company_eik", "company_mol", "company_address"):
                if not data.get(f):
                    self.add_error(f, "Задължително поле за фактура.")
        return data
