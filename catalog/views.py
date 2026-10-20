from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Exists, F, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.utils import safe_back
from orders.models import Order, OrderItem

from .models import Category, Product, ProductVariant, Review, WishlistItem

SORTS = {
    "popular": ("Най-популярни", ["-sales_count", "-created_at"]),
    "new": ("Най-нови", ["-created_at"]),
    "price_asc": ("Цена: ниска към висока", ["price"]),
    "price_desc": ("Цена: висока към ниска", ["-price"]),
    "rating": ("Най-високо оценени", ["-rating_avg", "-rating_count"]),
}
PAGE_SIZE = 12


def _decimal(value):
    try:
        return Decimal(value) if value not in (None, "") else None
    except InvalidOperation:
        return None


def product_list(request, slug=None, sale=False):
    category = None
    qs = (
        Product.objects.active()
        .select_related("category")
        .prefetch_related("images", "variants")
        .annotate(
            has_stock=Exists(
                ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True).filter(
                    Q(stock__gt=0) | Q(product__track_inventory=False)
                )
            )
        )
    )
    if slug:
        category = get_object_or_404(Category, slug=slug, is_active=True)
        qs = qs.filter(Q(category=category) | Q(category__parent=category))
    if sale:
        qs = qs.filter(compare_at_price__isnull=False, compare_at_price__gt=F("price"))

    q = request.GET.get("q", "").strip()
    if q:
        for term in q.lower().split()[:6]:
            qs = qs.filter(search_text__contains=term)

    materials = sorted({m for m in qs.values_list("material", flat=True) if m})
    material = request.GET.get("material", "")
    if material:
        qs = qs.filter(material=material)
    price_min, price_max = _decimal(request.GET.get("min")), _decimal(request.GET.get("max"))
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)
    if request.GET.get("in_stock"):
        qs = qs.filter(has_stock=True)

    sort = request.GET.get("sort", "popular")
    if sort not in SORTS:
        sort = "popular"
    qs = qs.order_by("-has_stock", *SORTS[sort][1])

    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    if sale:
        title, subtitle = "Промоции", "Избрани продукти на намалени цени."
    elif category:
        title, subtitle = category.name, category.tagline or category.description
    elif q:
        title, subtitle = f"Търсене: „{q}“", f"{page.paginator.count} намерени продукта"
    else:
        title, subtitle = "Магазин", "Открийте колекцията на Чаршафчето."

    return render(request, "catalog/shop.html", {
        "page_obj": page,
        "products": page.object_list,
        "current_category": category,
        "categories": Category.objects.filter(is_active=True, parent__isnull=True),
        "materials": materials,
        "sorts": [(k, v[0]) for k, v in SORTS.items()],
        "sort": sort,
        "q": q,
        "title": title,
        "subtitle": subtitle,
        "is_sale": sale,
        "has_filters": any(request.GET.get(k) for k in ("material", "min", "max", "in_stock")),
    })


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}


def has_purchased(user, product):
    return user.is_authenticated and OrderItem.objects.filter(
        order__user=user, product=product, order__status=Order.STATUS_DELIVERED
    ).exists()


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.active().select_related("category", "supplier").prefetch_related("images", "variants"),
        slug=slug,
    )
    variants = product.active_variants()
    reviews = product.reviews.filter(is_approved=True).select_related("user")
    related = (
        Product.objects.active().filter(category=product.category).exclude(pk=product.pk)
        .prefetch_related("images", "variants").order_by("-sales_count")[:4]
    )
    user_review = None
    if request.user.is_authenticated:
        user_review = product.reviews.filter(user=request.user).first()
    default_variant = next((v for v in variants if v.available), variants[0] if variants else None)
    return render(request, "catalog/product.html", {
        "product": product,
        "variants": variants,
        "default_variant": default_variant,
        "reviews": reviews,
        "review_form": ReviewForm(),
        "user_review": user_review,
        "can_review": request.user.is_authenticated and user_review is None,
        "related": related,
        "current_category": product.category,
    })


@require_POST
def review_create(request, slug):
    product = get_object_or_404(Product.objects.active(), slug=slug)
    if not request.user.is_authenticated:
        messages.error(request, "Влезте в профила си, за да оставите отзив.")
        return redirect(f"{product.get_absolute_url()}#reviews")
    form = ReviewForm(request.POST)
    if product.reviews.filter(user=request.user).exists():
        messages.error(request, "Вече сте оставили отзив за този продукт.")
    elif form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        review.name = request.user.get_full_name() or request.user.email.split("@")[0]
        review.is_verified = has_purchased(request.user, product)
        review.save()
        messages.success(request, "Благодарим! Отзивът ви ще бъде публикуван след преглед.")
    else:
        messages.error(request, "Моля, изберете оценка и напишете отзив.")
    return redirect(f"{product.get_absolute_url()}#reviews")


# --------------------------------------------------------------------------
# Wishlist: DB for logged-in users, session for guests (merged on login).
# --------------------------------------------------------------------------
def wishlist_ids(request):
    if request.user.is_authenticated:
        return list(WishlistItem.objects.filter(user=request.user).values_list("product_id", flat=True))
    return list(request.session.get("wishlist", []))


def wishlist(request):
    ids = wishlist_ids(request)
    products = Product.objects.active().filter(pk__in=ids).prefetch_related("images", "variants")
    return render(request, "catalog/wishlist.html", {"products": products})


@require_POST
def wishlist_toggle(request, product_id):
    product = get_object_or_404(Product.objects.active(), pk=product_id)
    if request.user.is_authenticated:
        item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
        if not created:
            item.delete()
        active = created
    else:
        ids = request.session.get("wishlist", [])
        active = product.pk not in ids
        ids = [*ids, product.pk] if active else [i for i in ids if i != product.pk]
        request.session["wishlist"] = ids
    message = "Добавено в любими" if active else "Премахнато от любими"
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "active": active, "product_id": product.pk, "message": message,
            "wishlist_count": len(wishlist_ids(request)),
        })
    messages.success(request, message)
    return redirect(safe_back(request, product.get_absolute_url()))
