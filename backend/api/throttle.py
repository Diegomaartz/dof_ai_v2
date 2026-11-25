"""Per-client fixed-window rate limit for the chat endpoint (each question spends Bedrock tokens)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.core.cache import cache
from django.http import HttpRequest

_PERIODS = {"second": 1, "minute": 60, "hour": 3600}


@dataclass(frozen=True)
class Rate:
    limit: int
    period_seconds: int

    @classmethod
    def parse(cls, value: str) -> Rate:
        """Parse ``"<n>/<second|minute|hour>"``, e.g. ``"10/minute"``."""
        try:
            count, unit = value.strip().split("/")
            return cls(int(count), _PERIODS[unit.strip().rstrip("s")])
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Invalid rate {value!r}; expected e.g. '10/minute'.") from exc


def client_ip(request: HttpRequest, trusted_proxy_count: int) -> str:
    """Client address. ``X-Forwarded-For`` is only trusted for the configured number of proxy hops."""
    remote = str(request.META.get("REMOTE_ADDR", "unknown"))
    if trusted_proxy_count <= 0:
        return remote
    forwarded = [h.strip() for h in str(request.META.get("HTTP_X_FORWARDED_FOR", "")).split(",") if h.strip()]
    return forwarded[-trusted_proxy_count] if len(forwarded) >= trusted_proxy_count else remote


async def check_rate(key: str, rate: Rate) -> int | None:
    """Count one request for ``key``. Returns ``None`` if allowed, else the seconds until the window resets."""
    now = int(time.time())
    window = now // rate.period_seconds
    cache_key = f"chat-rate:{key}:{window}"
    if await cache.aadd(cache_key, 1, timeout=rate.period_seconds):
        count = 1
    else:
        try:
            count = await cache.aincr(cache_key)
        except ValueError:  # expired between add and incr
            await cache.aset(cache_key, 1, timeout=rate.period_seconds)
            count = 1
    if count <= rate.limit:
        return None
    return rate.period_seconds - (now % rate.period_seconds) or 1
