from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ApiConfig(AppConfig):
    name = "api"
    verbose_name = "DOF-AI API v2"

    def ready(self) -> None:
        """Fail at startup, not on the first request, when the chat rate limit is misconfigured."""
        from api.throttle import Rate

        try:
            Rate.parse(settings.CHAT_RATE_LIMIT)
        except ValueError as exc:
            raise ImproperlyConfigured(f"CHAT_RATE_LIMIT: {exc}") from exc
