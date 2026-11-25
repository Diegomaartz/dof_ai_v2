"""WSGI entry point. Streaming chat needs ASGI (``core.asgi``); WSGI only suits management tooling."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

application = get_wsgi_application()
