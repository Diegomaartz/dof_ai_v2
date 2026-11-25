"""Django settings for the DOF-AI v2 API. Every deploy-specific value comes from environment variables.

The API is stateless: no database, sessions or auth apps. Answers come from the LangGraph agent and
nothing is persisted. In AWS, ``DJANGO_SECRET_KEY`` is injected into the ECS task from Secrets Manager.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = _bool("DJANGO_DEBUG")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=true for local development).")
    SECRET_KEY = "insecure-local-development-key-do-not-use-in-production"

ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"
ASGI_APPLICATION = "core.asgi.application"
WSGI_APPLICATION = "core.wsgi.application"

DATABASES: dict[str, dict[str, str]] = {}

CACHES = {
    # Per-process cache backing the chat rate limiter; one ECS task means one counter.
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "dof-ai"},
}

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

# --- Security headers (the API is served over HTTPS in AWS) ---
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if _bool("DJANGO_BEHIND_TLS_PROXY") else None

# --- CORS: the React SPA is hosted on a different origin (S3) ---
CORS_ALLOWED_ORIGINS = _csv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173" if DEBUG else "")
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_URLS_REGEX = r"^/api/.*$"

# --- Django REST Framework: no authentication backends, so no auth/contenttypes apps are needed ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

# --- Chat endpoint ---
DOF_AGENT_FACTORY = os.getenv("DOF_AGENT_FACTORY", "agent.factory.build_default_agent")
"""Dotted path of a zero-argument callable returning the compiled agent graph (tests swap in fakes)."""

CHAT_MAX_QUESTION_CHARS = int(os.getenv("CHAT_MAX_QUESTION_CHARS", "2000"))
CHAT_RATE_LIMIT = os.getenv("CHAT_RATE_LIMIT", "10/minute")
"""Questions allowed per client IP; every question spends Bedrock tokens. Format: <n>/(second|minute|hour)."""
CHAT_TRUSTED_PROXY_COUNT = int(os.getenv("CHAT_TRUSTED_PROXY_COUNT", "0"))
"""Reverse proxies in front of Django whose X-Forwarded-For entries are trusted (0: use the socket address)."""
CHAT_KEEPALIVE_SECONDS = float(os.getenv("CHAT_KEEPALIVE_SECONDS", "15"))
"""SSE comment sent while the agent is silent, so proxies do not drop the connection."""

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
