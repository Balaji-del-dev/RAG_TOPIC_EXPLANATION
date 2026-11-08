"""URL configuration for the Session & Conversation Management service."""

from django.contrib import admin
from django.urls import include, path

from conversations.web import how_it_works, playground

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("api/v1/", include("conversations.urls")),
    path("how-it-works", how_it_works, name="how-it-works"),
    path("", playground, name="playground"),
]
