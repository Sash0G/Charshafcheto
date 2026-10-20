from django.urls import path

from .views import content, crud, home, orders, people, products

app_name = "dashboard"


def entity_urls(key):
    return [
        path(f"{key}/", crud.entity_list, {"entity": key}, name=key),
        path(f"{key}/new/", crud.entity_form, {"entity": key}, name=f"{key}_create"),
        path(f"{key}/<int:pk>/edit/", crud.entity_form, {"entity": key}, name=f"{key}_edit"),
        path(f"{key}/<int:pk>/delete/", crud.entity_delete, {"entity": key}, name=f"{key}_delete"),
    ]


urlpatterns = [
    path("", home.home, name="home"),
    # orders
    path("orders/", orders.order_list, name="orders"),
    path("orders/export/", orders.order_export, name="orders_export"),
    path("orders/<int:pk>/", orders.order_detail, name="order_detail"),
    path("orders/<int:pk>/status/", orders.order_status, name="order_status"),
    path("orders/<int:pk>/payment/", orders.order_payment, name="order_payment"),
    path("orders/<int:pk>/tracking/", orders.order_tracking, name="order_tracking"),
    path("orders/<int:pk>/note/", orders.order_note, name="order_note"),
    path("orders/<int:pk>/forward/", orders.order_forward, name="order_forward"),
    path("orders/<int:pk>/supplier/<int:so_pk>/", orders.supplier_order_update, name="supplier_order_update"),
    path("orders/<int:pk>/print/", orders.order_print, name="order_print"),
    # products
    path("products/", products.product_list, name="products"),
    path("products/new/", products.product_create, name="product_create"),
    path("products/bulk/", products.product_bulk, name="product_bulk"),
    path("products/export/", products.product_export, name="product_export"),
    path("products/import/", products.product_import, name="product_import"),
    path("products/<int:pk>/edit/", products.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", products.product_delete, name="product_delete"),
    path("products/<int:pk>/toggle/", products.product_toggle, name="product_toggle"),
    path("products/<int:pk>/duplicate/", products.product_duplicate, name="product_duplicate"),
    path("variants/<int:pk>/stock/", products.variant_stock, name="variant_stock"),
    # simple entities
    *entity_urls("categories"),
    *entity_urls("suppliers"),
    path("suppliers/<int:pk>/", crud.supplier_detail, name="supplier_detail"),
    *entity_urls("coupons"),
    *entity_urls("shipping"),
    *entity_urls("pages"),
    # people
    path("customers/", people.customer_list, name="customers"),
    path("customers/guest/", people.guest_detail, name="guest_detail"),
    path("customers/<int:pk>/", people.customer_detail, name="customer_detail"),
    path("team/", people.team, name="team"),
    path("team/<int:pk>/", people.team_toggle, name="team_toggle"),
    # content & moderation
    path("reviews/", content.review_list, name="reviews"),
    path("reviews/<int:pk>/", content.review_action, name="review_action"),
    path("messages/", content.message_list, name="messages"),
    path("messages/<int:pk>/", content.message_detail, name="message_detail"),
    path("messages/<int:pk>/action/", content.message_action, name="message_action"),
    path("subscribers/", content.subscriber_list, name="subscribers"),
    path("subscribers/<int:pk>/toggle/", content.subscriber_toggle, name="subscriber_toggle"),
    # system
    path("settings/", content.site_settings, name="settings"),
    path("audit/", content.audit_log, name="audit"),
]
