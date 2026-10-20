from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Чаршафчето — системна администрация"

urlpatterns = [
    path("", include("core.urls")),
    path("shop/", include("catalog.urls")),
    path("cart/", include("cart.urls")),
    path("checkout/", include("orders.urls")),
    path("account/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
