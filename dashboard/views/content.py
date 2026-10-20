import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import Review
from core.models import AuditLog, ContactMessage, NewsletterSubscriber, SiteSettings

from ..access import paginate, safe_next, staff_required, superuser_required
from ..forms import SiteSettingsForm


# ---- reviews ---------------------------------------------------------------
@staff_required
def review_list(request):
    tab = request.GET.get("tab", "pending")
    qs = Review.objects.select_related("product", "user").filter(is_approved=tab == "approved")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(name__icontains=q) | Q(body__icontains=q))
    return render(request, "dashboard/reviews/list.html", {
        "page": paginate(request, qs),
        "tab": tab,
        "n_pending": Review.objects.filter(is_approved=False).count(),
        "n_approved": Review.objects.filter(is_approved=True).count(),
    })


@staff_required
@require_POST
def review_action(request, pk):
    review = get_object_or_404(Review.objects.select_related("product"), pk=pk)
    product = review.product
    action = request.POST.get("action")
    if action == "approve":
        review.is_approved = True
        review.save(update_fields=["is_approved"])
        messages.success(request, "Отзивът е одобрен и публикуван.")
    elif action == "unapprove":
        review.is_approved = False
        review.save(update_fields=["is_approved"])
        messages.success(request, "Отзивът е скрит.")
    elif action == "delete":
        review.delete()
        messages.success(request, "Отзивът е изтрит.")
    else:
        return redirect("dashboard:reviews")
    product.refresh_rating()
    AuditLog.record(request, f"review_{action}", product, f"Отзив за „{product}“: {action}")
    return redirect(safe_next(request, "dashboard:reviews"))


# ---- inbox & newsletter --------------------------------------------------
@staff_required
def message_list(request):
    qs = ContactMessage.objects.all()
    if request.GET.get("unread"):
        qs = qs.filter(is_read=False)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))
    return render(request, "dashboard/messages/list.html", {
        "page": paginate(request, qs), "n_unread": ContactMessage.objects.filter(is_read=False).count(),
    })


@staff_required
def message_detail(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    if not msg.is_read:
        msg.is_read = True
        msg.save(update_fields=["is_read"])
    return render(request, "dashboard/messages/detail.html", {"msg": msg})


@staff_required
@require_POST
def message_action(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    if request.POST.get("action") == "delete":
        AuditLog.record(request, "delete", msg)
        msg.delete()
        messages.success(request, "Съобщението е изтрито.")
    else:
        msg.is_read = False
        msg.save(update_fields=["is_read"])
        messages.success(request, "Маркирано като непрочетено.")
    return redirect("dashboard:messages")


@staff_required
def subscriber_list(request):
    qs = NewsletterSubscriber.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(email__icontains=q)
    if request.GET.get("export"):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="subscribers-{timezone.localdate():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["email", "active", "subscribed_at"])
        for s in qs.filter(is_active=True):
            writer.writerow([s.email, int(s.is_active), timezone.localtime(s.created_at).strftime("%Y-%m-%d %H:%M")])
        return response
    return render(request, "dashboard/messages/subscribers.html", {
        "page": paginate(request, qs), "n_active": NewsletterSubscriber.objects.filter(is_active=True).count(),
    })


@staff_required
@require_POST
def subscriber_toggle(request, pk):
    sub = get_object_or_404(NewsletterSubscriber, pk=pk)
    sub.is_active = not sub.is_active
    sub.save(update_fields=["is_active"])
    messages.success(request, f"{sub.email}: {'активен' if sub.is_active else 'отписан'}.")
    return redirect("dashboard:subscribers")


# ---- settings & audit -----------------------------------------------------
@superuser_required
def site_settings(request):
    instance = SiteSettings.load()
    form = SiteSettingsForm(request.POST or None, instance=instance)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            AuditLog.record(request, "update", instance, "Настройките на магазина са променени")
            messages.success(request, "Настройките са записани.")
            return redirect("dashboard:settings")
        messages.error(request, "Моля, коригирайте грешките във формата.")
    return render(request, "dashboard/settings.html", {"form": form})


@staff_required
def audit_log(request):
    qs = AuditLog.objects.select_related("user")
    if request.GET.get("user"):
        qs = qs.filter(user_id=request.GET["user"])
    if request.GET.get("type"):
        qs = qs.filter(object_type=request.GET["type"])
    if request.GET.get("action"):
        qs = qs.filter(action=request.GET["action"])
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(summary__icontains=q)
    return render(request, "dashboard/audit.html", {
        "page": paginate(request, qs),
        "users": get_user_model().objects.filter(is_staff=True),
        "types": AuditLog.objects.values_list("object_type", flat=True).distinct().order_by("object_type"),
        "actions": AuditLog.objects.values_list("action", flat=True).distinct().order_by("action"),
    })
