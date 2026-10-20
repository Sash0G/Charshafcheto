from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.product_list, name="shop"),
    path("c/<slug:slug>/", views.product_list, name="category"),
    path("promotions/", views.product_list, {"sale": True}, name="sale"),
    path("p/<slug:slug>/", views.product_detail, name="product"),
    path("p/<slug:slug>/review/", views.review_create, name="review"),
    path("wishlist/", views.wishlist, name="wishlist"),
    path("wishlist/toggle/<int:product_id>/", views.wishlist_toggle, name="wishlist_toggle"),
]
