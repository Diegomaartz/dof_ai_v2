"""Routes under ``/api/v2/``."""

from django.urls import path

from api.views import HealthView, chat_view

urlpatterns = [
    path("chat/", chat_view, name="chat"),
    path("health/", HealthView.as_view(), name="health"),
]
