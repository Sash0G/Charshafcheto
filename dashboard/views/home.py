from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from catalog.models import ProductVariant, Review
from core.models import ContactMessage, SiteSettings
from orders.models import Order, OrderItem

from ..access import staff_required

PERIODS = {"7": 7, "30": 30, "90": 90}
CHART_W, CHART_H, CHART_PAD_L, CHART_PAD_B, CHART_PAD_T = 760, 240, 52, 26, 14


def _nice_ceiling(value):
    """Round the axis maximum up to a readable number (1, 2, 2.5, 5 × 10^n)."""
    if value <= 0:
        return Decimal("10")
    magnitude = Decimal(10) ** (len(str(int(value))) - 1)
    for step in (1, 2, Decimal("2.5"), 5, 10):
        if value <= magnitude * step:
            return magnitude * step
    return magnitude * 10


def revenue_chart(start_date, days, by_day):
    """Geometry for a single-series bar chart drawn as inline SVG."""
    values = [by_day.get(start_date + timedelta(days=i), Decimal("0")) for i in range(days)]
    top = _nice_ceiling(max(values) if values else Decimal("0"))
    plot_w = CHART_W - CHART_PAD_L - 8
    plot_h = CHART_H - CHART_PAD_B - CHART_PAD_T
    slot = plot_w / days
    bar_w = max(2.0, min(28.0, slot - 2))  # 2px surface gap between adjacent bars
    bars = []
    label_every = 1 if days <= 7 else (5 if days <= 30 else 15)
    for i, value in enumerate(values):
        h = float(value / top) * plot_h if top else 0
        x = CHART_PAD_L + i * slot + (slot - bar_w) / 2
        day = start_date + timedelta(days=i)
        top_y = CHART_PAD_T + plot_h - h
        r = min(4.0, bar_w / 2, h)
        base_y = CHART_PAD_T + plot_h
        path = (
            f"M{x:.1f},{base_y:.1f}V{top_y + r:.1f}Q{x:.1f},{top_y:.1f} {x + r:.1f},{top_y:.1f}"
            f"H{x + bar_w - r:.1f}Q{x + bar_w:.1f},{top_y:.1f} {x + bar_w:.1f},{top_y + r:.1f}V{base_y:.1f}Z"
        ) if h > 0 else ""
        bars.append({
            "path": path,
            "x": round(x, 1), "y": round(CHART_PAD_T + plot_h - h, 1), "w": round(bar_w, 1), "h": round(h, 1),
            "hit_x": round(CHART_PAD_L + i * slot, 1), "hit_w": round(slot, 1),
            "value": value, "date": day, "label": i % label_every == 0 or i == days - 1,
            "cx": round(x + bar_w / 2, 1),
        })
    gridlines = []
    for i in range(5):
        v = top * i / 4
        gridlines.append({"y": round(CHART_PAD_T + plot_h - plot_h * i / 4, 1), "value": v})
    return {
        "bars": bars, "grid": gridlines, "w": CHART_W, "h": CHART_H, "pad_l": CHART_PAD_L,
        "baseline": CHART_PAD_T + plot_h, "label_y": CHART_H - 8, "right": CHART_W - 8,
        "has_data": any(values),
    }


@staff_required
def home(request):
    period_key = request.GET.get("period", "30")
    days = PERIODS.get(period_key, 30)
    now = timezone.now()
    today = timezone.localdate()
    start_date = today - timedelta(days=days - 1)
    start = timezone.make_aware(datetime.combine(start_date, time.min))
    prev_start = start - timedelta(days=days)

    counted = Order.objects.exclude(status__in=Order.REVENUE_EXCLUDED)
    current = counted.filter(created_at__gte=start)
    previous = counted.filter(created_at__gte=prev_start, created_at__lt=start)

    def summarize(qs):
        agg = qs.aggregate(revenue=Sum("total"), shipping=Sum("shipping_total"), cost=Sum("cost_total"), n=Count("id"))
        revenue = agg["revenue"] or Decimal("0")
        profit = revenue - (agg["shipping"] or 0) - (agg["cost"] or 0)
        return {
            "revenue": revenue, "orders": agg["n"], "profit": profit,
            "aov": (revenue / agg["n"]) if agg["n"] else Decimal("0"),
            "margin": (profit / revenue * 100) if revenue else Decimal("0"),
        }

    cur, prev = summarize(current), summarize(previous)

    def delta(key):
        if not prev[key]:
            return None
        return round((cur[key] - prev[key]) / prev[key] * 100)

    User = get_user_model()
    new_customers = User.objects.filter(is_staff=False, date_joined__gte=start).count()

    by_day = {
        row["day"]: row["revenue"]
        for row in current.annotate(day=TruncDate("created_at")).values("day").annotate(revenue=Sum("total"))
    }

    line_revenue = ExpressionWrapper(F("unit_price") * F("quantity"), output_field=DecimalField())
    top_products = (
        OrderItem.objects.filter(order__in=current)
        .values("product_id", "product_name")
        .annotate(units=Sum("quantity"), revenue=Sum(line_revenue))
        .order_by("-units")[:5]
    )

    store = SiteSettings.load()
    low_stock = (
        ProductVariant.objects.filter(
            is_active=True, product__is_active=True, product__track_inventory=True,
            stock__lte=store.low_stock_threshold,
        )
        .select_related("product")
        .order_by("stock")[:10]
    )

    context = {
        "period": str(days),
        "periods": PERIODS,
        "kpi": cur,
        "deltas": {k: delta(k) for k in ("revenue", "orders", "aov", "profit")},
        "new_customers": new_customers,
        "chart": revenue_chart(start_date, days, by_day),
        "top_products": top_products,
        "low_stock": low_stock,
        "recent_orders": Order.objects.select_related("user")[:8],
        "attention": {
            "new": Order.objects.filter(status=Order.STATUS_NEW).count(),
            "to_forward": Order.objects.filter(status=Order.STATUS_CONFIRMED).count(),
            "pending_payment": Order.objects.filter(
                status=Order.STATUS_PENDING_PAYMENT, created_at__lt=now - timedelta(hours=1)
            ).count(),
            "messages": ContactMessage.objects.filter(is_read=False).count(),
            "reviews": Review.objects.filter(is_approved=False).count(),
        },
    }
    return render(request, "dashboard/home.html", context)
