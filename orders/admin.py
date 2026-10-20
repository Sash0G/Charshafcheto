from django.contrib import admin

from .models import Coupon, Order, OrderEvent, OrderItem, ShippingMethod, SupplierOrder


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class EventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["number", "full_name", "email", "status", "payment_status", "total", "created_at"]
    list_filter = ["status", "payment_status", "payment_method"]
    search_fields = ["number", "email", "full_name", "phone"]
    inlines = [ItemInline, EventInline]


admin.site.register(Coupon)
admin.site.register(ShippingMethod)
admin.site.register(SupplierOrder)
