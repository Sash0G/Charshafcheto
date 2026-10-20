from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import AuditLog
from orders.models import Order

from ..access import paginate, staff_required, superuser_required
from ..forms import StaffCreateForm

User = get_user_model()

COUNTED = ~Q(orders__status__in=Order.REVENUE_EXCLUDED)


@staff_required
def customer_list(request):
    tab = request.GET.get("tab", "registered")
    q = request.GET.get("q", "").strip()
    if tab == "guests":
        qs = Order.objects.filter(user__isnull=True)
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q) | Q(phone__icontains=q))
        qs = (
            qs.values("email")
            .annotate(
                name=Max("full_name"), phone=Max("phone"), n_orders=Count("id"),
                spent=Sum("total", filter=~Q(status__in=Order.REVENUE_EXCLUDED)), last_order=Max("created_at"),
            )
            .order_by("-last_order")
        )
    else:
        qs = User.objects.filter(is_staff=False)
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(phone__icontains=q))
        qs = qs.annotate(
            n_orders=Count("orders", distinct=True),
            spent=Sum("orders__total", filter=COUNTED),
            last_order=Max("orders__created_at"),
        ).order_by("-date_joined")
    return render(request, "dashboard/customers/list.html", {
        "page": paginate(request, qs),
        "tab": tab,
        "n_registered": User.objects.filter(is_staff=False).count(),
        "n_guests": Order.objects.filter(user__isnull=True).values("email").distinct().count(),
    })


@staff_required
def customer_detail(request, pk):
    customer = get_object_or_404(User, pk=pk)
    orders = customer.orders.all()
    stats = orders.exclude(status__in=Order.REVENUE_EXCLUDED).aggregate(spent=Sum("total"), n=Count("id"))
    return render(request, "dashboard/customers/detail.html", {
        "customer": customer,
        "addresses": customer.addresses.all(),
        "orders": orders[:50],
        "n_orders": orders.count(),
        "spent": stats["spent"] or 0,
        "aov": (stats["spent"] / stats["n"]) if stats["n"] else 0,
        "wishlist_count": customer.wishlist.count(),
        "reviews_count": customer.reviews.count(),
    })


@staff_required
def guest_detail(request):
    email = request.GET.get("email", "")
    orders = Order.objects.filter(user__isnull=True, email__iexact=email)
    if not orders.exists():
        messages.error(request, "Няма поръчки за този имейл.")
        return redirect("dashboard:customers")
    stats = orders.exclude(status__in=Order.REVENUE_EXCLUDED).aggregate(spent=Sum("total"), n=Count("id"))
    return render(request, "dashboard/customers/guest.html", {
        "email": email, "orders": orders, "latest": orders.first(), "spent": stats["spent"] or 0,
    })


@superuser_required
def team(request):
    form = StaffCreateForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            AuditLog.record(request, "create", user, f"Нов член на екипа: {user.email}")
            messages.success(request, f"{user.email} е добавен към екипа.")
            return redirect("dashboard:team")
        messages.error(request, "Моля, коригирайте грешките във формата.")
    return render(request, "dashboard/team.html", {
        "form": form,
        "staff": User.objects.filter(is_staff=True).order_by("-is_superuser", "email"),
    })


@superuser_required
@require_POST
def team_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "Не можете да промените собствените си права.")
        return redirect("dashboard:team")
    action = request.POST.get("action")
    if action == "remove":
        user.is_staff = user.is_superuser = False
        msg = f"{user.email} вече няма достъп до админ панела."
    elif action == "superuser":
        user.is_superuser = not user.is_superuser
        msg = f"{user.email}: пълни права {'дадени' if user.is_superuser else 'отнети'}."
    else:
        return redirect("dashboard:team")
    user.save(update_fields=["is_staff", "is_superuser"])
    AuditLog.record(request, "permissions", user, msg)
    messages.success(request, msg)
    return redirect("dashboard:team")
