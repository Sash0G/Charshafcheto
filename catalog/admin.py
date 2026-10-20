from django.contrib import admin

from .models import Category, Product, ProductImage, ProductVariant, Review, Supplier


class VariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "sku", "category", "supplier", "price", "cost_price", "is_active"]
    list_filter = ["is_active", "category", "supplier"]
    search_fields = ["name", "sku"]
    inlines = [VariantInline, ImageInline]


admin.site.register(Category)
admin.site.register(Supplier)
admin.site.register(Review)
