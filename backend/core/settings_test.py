"""Settings for pytest and mypy: deterministic values, fake agent, no external services."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from core.settings import *  # noqa: F403

DOF_AGENT_FACTORY = "tests.api.fakes.build_fake_agent"
CHAT_RATE_LIMIT = "1000/minute"
CHAT_KEEPALIVE_SECONDS = 15.0
