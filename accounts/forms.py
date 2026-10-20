from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.core.cache import cache

from core.utils import client_ip

from .models import Address, User

MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


class LoginForm(AuthenticationForm):
    """Email login with a per-IP+email lockout after repeated failures."""

    username = forms.EmailField(label="Имейл", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Грешен имейл или парола.",
        "locked": "Твърде много неуспешни опити. Опитайте отново след 15 минути.",
    }

    def _key(self):
        return f"login-fail:{client_ip(self.request)}:{(self.data.get('username') or '').lower()}"

    def clean(self):
        if self.request and cache.get(self._key(), 0) >= MAX_LOGIN_FAILURES:
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            return super().clean()
        except forms.ValidationError:
            if self.request:
                key = self._key()
                cache.set(key, cache.get(key, 0) + 1, LOCKOUT_SECONDS)
            raise


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="Парола", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text="Поне 8 символа, не само цифри.")
    password2 = forms.CharField(label="Повторете паролата", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(label="Приемам общите условия и политиката за поверителност")
    website = forms.CharField(required=False)  # honeypot

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "marketing_consent"]
        labels = {"first_name": "Име", "last_name": "Фамилия", "marketing_consent": "Искам да получавам промоции и новини по имейл"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["email"].widget.attrs["autocomplete"] = "email"

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Вече има профил с този имейл. Опитайте да влезете или да възстановите паролата си.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Паролите не съвпадат.")
        elif p1:
            user = User(email=data.get("email", ""), first_name=data.get("first_name", ""))
            try:
                password_validation.validate_password(p1, user)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "marketing_consent"]
        labels = {"first_name": "Име", "last_name": "Фамилия", "marketing_consent": "Искам да получавам промоции и новини по имейл"}


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ["label", "full_name", "phone", "city", "postcode", "line1", "is_default"]


class StyledPasswordChangeForm(PasswordChangeForm):
    pass


class StyledPasswordResetForm(PasswordResetForm):
    pass


class StyledSetPasswordForm(SetPasswordForm):
    pass


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label="Потвърдете с паролата си", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError("Грешна парола.")
        return self.cleaned_data["password"]
