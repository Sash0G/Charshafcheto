from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("verify/<str:token>/", views.verify_email, name="verify"),
    path("verify-resend/", views.resend_verification, name="verify_resend"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/done/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.orders, name="orders"),
    path("profile/", views.profile, name="profile"),
    path("addresses/", views.addresses, name="addresses"),
    path("addresses/add/", views.address_edit, name="address_add"),
    path("addresses/<int:pk>/edit/", views.address_edit, name="address_edit"),
    path("addresses/<int:pk>/delete/", views.address_delete, name="address_delete"),
    path("wishlist/", RedirectView.as_view(pattern_name="catalog:wishlist"), name="wishlist"),
    path("privacy/export/", views.export_data, name="export"),
    path("privacy/delete/", views.delete_account, name="delete"),
]
