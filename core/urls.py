from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("page/<slug:slug>/", views.page, name="page"),
    path("contact/", views.contact, name="contact"),
    path("newsletter/", views.newsletter, name="newsletter"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
    path("cookies/", RedirectView.as_view(url="/page/biskvitki/"), name="cookies"),
]
