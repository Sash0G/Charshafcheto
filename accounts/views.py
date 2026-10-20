import json

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import WishlistItem
from core.views import rate_limited
from orders.models import Order
from orders.services import send_templated_email

from .forms import (
    AddressForm,
    DeleteAccountForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from .models import Address, User

VERIFY_SALT = "accounts.verify-email"
VERIFY_MAX_AGE = 60 * 60 * 24 * 3


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


def send_verification(request, user):
    token = signing.dumps({"uid": user.pk, "email": user.email}, salt=VERIFY_SALT)
    url = request.build_absolute_uri(reverse("accounts:verify", args=[token]))
    send_templated_email("Потвърдете имейла си", "verify_email", {"user": user, "url": url}, [user.email])


def link_guest_orders(user):
    """Attach past guest orders placed with this (verified) email."""
    return Order.objects.filter(user__isnull=True, email__iexact=user.email).update(user=user)


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    form = RegisterForm(request.POST or None, initial={"email": request.GET.get("email", "")})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("website") or rate_limited(request, "register", 10):
            return redirect("accounts:register")
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        send_verification(request, user)
        messages.success(request, "Профилът е създаден! Изпратихме ви имейл за потвърждение.")
        nxt = request.GET.get("next", "")
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            nxt = "accounts:dashboard"
        return redirect(nxt)
    return render(request, "accounts/register.html", {"form": form})


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
    except signing.BadSignature:
        messages.error(request, "Линкът за потвърждение е невалиден или е изтекъл.")
        return redirect("accounts:dashboard")
    user = User.objects.filter(pk=data["uid"], email=data["email"]).first()
    if user is None:
        messages.error(request, "Линкът за потвърждение е невалиден.")
        return redirect("core:home")
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        linked = link_guest_orders(user)
        msg = "Имейлът е потвърден."
        if linked:
            msg += f" Добавихме {linked} предишни поръчки към профила ви."
        messages.success(request, msg)
    return redirect("accounts:dashboard")


@login_required
@require_POST
def resend_verification(request):
    if not request.user.email_verified and not rate_limited(request, "verify", 5):
        send_verification(request, request.user)
    messages.success(request, "Изпратихме нов имейл за потвърждение.")
    return redirect("accounts:dashboard")


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = StyledPasswordResetForm
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        if rate_limited(self.request, "pwreset", 5):
            return redirect(self.success_url)
        return super().form_valid(form)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Паролата е сменена.")
        return super().form_valid(form)


# --------------------------------------------------------------------------
# Account area
# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    orders = request.user.orders.prefetch_related("items")
    return render(request, "accounts/dashboard.html", {
        "tab": "dashboard",
        "recent_orders": orders[:3],
        "orders_count": orders.count(),
        "open_count": orders.filter(status__in=Order.OPEN_STATUSES).count(),
        "wishlist_count": WishlistItem.objects.filter(user=request.user).count(),
        "default_address": request.user.addresses.first(),
    })


@login_required
def orders(request):
    return render(request, "accounts/orders.html", {
        "tab": "orders",
        "orders": request.user.orders.prefetch_related("items"),
    })


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Промените са записани.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"tab": "profile", "form": form})


@login_required
def addresses(request):
    return render(request, "accounts/addresses.html", {"tab": "addresses", "addresses": request.user.addresses.all()})


@login_required
def address_edit(request, pk=None):
    address = get_object_or_404(Address, pk=pk, user=request.user) if pk else None
    form = AddressForm(request.POST or None, instance=address, initial=None if address else {
        "full_name": request.user.get_full_name(), "phone": request.user.phone,
        "is_default": not request.user.addresses.exists(),
    })
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, "Адресът е записан.")
        return redirect("accounts:addresses")
    return render(request, "accounts/address_form.html", {"tab": "addresses", "form": form, "address": address})


@login_required
@require_POST
def address_delete(request, pk):
    get_object_or_404(Address, pk=pk, user=request.user).delete()
    messages.success(request, "Адресът е изтрит.")
    return redirect("accounts:addresses")


@login_required
def export_data(request):
    """GDPR art. 20 — download everything we store about the customer."""
    user = request.user
    data = {
        "exported_at": timezone.now().isoformat(),
        "profile": {
            "email": user.email, "first_name": user.first_name, "last_name": user.last_name, "phone": user.phone,
            "marketing_consent": user.marketing_consent, "date_joined": user.date_joined.isoformat(),
        },
        "addresses": list(user.addresses.values("label", "full_name", "phone", "city", "postcode", "line1")),
        "orders": [
            {
                "number": o.number, "date": o.created_at.isoformat(), "status": o.get_status_display(),
                "total": str(o.total), "currency": o.currency, "delivery": f"{o.city}, {o.address}",
                "items": [{"product": i.product_name, "variant": i.variant_name, "qty": i.quantity,
                           "price": str(i.unit_price)} for i in o.items.all()],
            }
            for o in user.orders.prefetch_related("items")
        ],
        "reviews": list(user.reviews.values("product__name", "rating", "title", "body", "created_at")),
        "wishlist": list(WishlistItem.objects.filter(user=user).values_list("product__name", flat=True)),
    }
    response = HttpResponse(json.dumps(data, ensure_ascii=False, indent=2, default=str), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="moite-danni.json"'
    return response


@login_required
def delete_account(request):
    """GDPR art. 17 — delete the account; orders are kept (accounting law) but detached."""
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        if user.is_staff:
            messages.error(request, "Служебните профили се изтриват от администратор.")
            return redirect("accounts:profile")
        user.orders.update(user=None)
        logout(request)
        user.delete()
        messages.success(request, "Профилът ви е изтрит.")
        return redirect("core:home")
    return render(request, "accounts/delete.html", {"tab": "profile", "form": form})
