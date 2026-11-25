"""Root URL configuration: the versioned public API."""

from django.urls import include, path

urlpatterns = [
    path("api/v2/", include("api.urls")),
]
