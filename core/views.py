from django import forms
from django.contrib import messages
from django.contrib.sitemaps import Sitemap
from django.contrib.sitemaps.views import sitemap as sitemap_view
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalog.models import Category, Product, Review
from orders.services import send_templated_email

from .models import ContactMessage, NewsletterSubscriber, Page, SiteSettings
from .utils import client_ip, safe_back


def home(request):
    products = Product.objects.active().select_related("category").prefetch_related("images", "variants")
    featured = list(products.filter(is_featured=True)[:4]) or list(products.order_by("-sales_count")[:4])
    return render(request, "core/home.html", {
        "categories": Category.objects.filter(is_active=True, parent__isnull=True)[:4],
        "featured": featured,
        "new_arrivals": products.order_by("-created_at")[:4],
        "testimonials": Review.objects.filter(is_approved=True, rating__gte=4).select_related("product")[:3],
    })


def page(request, slug):
    return render(request, "core/page.html", {"page": get_object_or_404(Page, slug=slug)})


def rate_limited(request, key, limit, window=3600):
    """Simple per-IP throttle for public forms."""
    cache_key = f"rl:{key}:{client_ip(request)}"
    hits = cache.get(cache_key, 0)
    if hits >= limit:
        return True
    cache.set(cache_key, hits + 1, window)
    return False


class ContactForm(forms.ModelForm):
    website = forms.CharField(required=False)  # honeypot

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 6})}


def contact(request):
    form = ContactForm(request.POST or None, initial={
        "name": request.user.get_full_name() if request.user.is_authenticated else "",
        "email": request.user.email if request.user.is_authenticated else "",
        "subject": request.GET.get("subject", "")[:160],
    })
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("website"):
            return redirect("core:contact")  # bot
        if rate_limited(request, "contact", 5):
            messages.error(request, "Изпратихте твърде много съобщения. Опитайте отново по-късно.")
            return redirect("core:contact")
        msg = form.save()
        store = SiteSettings.load()
        send_templated_email(f"Ново съобщение: {msg.subject}", "contact_notification", {"msg": msg},
                             [store.contact_email], reply_to=[msg.email])
        messages.success(request, "Благодарим ви! Ще се свържем с вас до 1 работен ден.")
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})


@require_POST
def newsletter(request):
    email = (request.POST.get("email") or "").strip().lower()
    try:
        forms.EmailField().clean(email)
    except forms.ValidationError:
        messages.error(request, "Моля, въведете валиден имейл адрес.")
    else:
        if not rate_limited(request, "newsletter", 10):
            NewsletterSubscriber.objects.update_or_create(email=email, defaults={"is_active": True})
        messages.success(request, "Успешно се абонирахте за нашия бюлетин.")
    return redirect(safe_back(request, "core:home"))


def robots(request):
    lines = [
        "User-agent: *",
        "Disallow: /dashboard/",
        "Disallow: /django-admin/",
        "Disallow: /account/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        f"Sitemap: {request.build_absolute_uri(reverse('core:sitemap'))}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Product.objects.active().order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Category.objects.filter(is_active=True).order_by("pk")


class StaticSitemap(Sitemap):
    priority = 0.5

    def items(self):
        return ["core:home", "catalog:shop", "catalog:sale", "core:contact"]

    def location(self, item):
        return reverse(item)


class PageSitemap(Sitemap):
    priority = 0.3

    def items(self):
        return Page.objects.all()


SITEMAPS = {"static": StaticSitemap, "categories": CategorySitemap, "products": ProductSitemap, "pages": PageSitemap}


def sitemap(request):
    return sitemap_view(request, sitemaps=SITEMAPS)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
