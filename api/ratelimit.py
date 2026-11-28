"""Fixed-window rate limits stored in the database (shared across workers)."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .errors import ApiError
from .models import RateLimitBucket


def hit(key: str, *, limit: int, window_seconds: int, message: str = '') -> int:
    """Count one event for `key`. Raises resource-exhausted past `limit`.

    Returns the count in the current window, including this event.
    """
    now = timezone.now()
    with transaction.atomic():
        bucket, _ = RateLimitBucket.objects.select_for_update().get_or_create(
            key=key[:200], defaults={'window_start': now, 'count': 0},
        )
        if now - bucket.window_start >= timedelta(seconds=window_seconds):
            bucket.window_start = now
            bucket.count = 0
        if bucket.count >= limit:
            retry_after = int(
                window_seconds - (now - bucket.window_start).total_seconds()
            )
            raise ApiError(
                'resource-exhausted',
                message or 'Too many attempts. Please wait a few minutes and try again.',
                extra={'retryAfterSeconds': max(retry_after, 1)},
            )
        bucket.count += 1
        bucket.save(update_fields=['window_start', 'count'])
        return bucket.count


def seen_once(key: str, *, window_seconds: int) -> bool:
    """True the first time `key` is seen in the window, False afterwards."""
    try:
        hit(key, limit=1, window_seconds=window_seconds)
        return True
    except ApiError:
        return False
