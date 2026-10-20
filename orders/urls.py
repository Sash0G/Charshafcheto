from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("", views.checkout, name="checkout"),
    path("success/<uuid:token>/", views.success, name="success"),
    path("order/<uuid:token>/", views.detail, name="detail"),
    path("order/<uuid:token>/cancel/", views.cancel, name="cancel"),
    path("order/<uuid:token>/invoice/", views.receipt, name="invoice"),
    path("track/", views.track, name="track"),
    path("pay/<uuid:token>/", views.pay, name="pay"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
