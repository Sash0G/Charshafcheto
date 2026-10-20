from django.contrib import admin

from .models import AuditLog, ContactMessage, NewsletterSubscriber, Page, SiteSettings

admin.site.register(SiteSettings)
admin.site.register(Page)
admin.site.register(ContactMessage)
admin.site.register(NewsletterSubscriber)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "action", "object_type", "summary"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]
