"""
Rate limiters that "fail open".

Request counts live in the cache (Redis). If Redis is unreachable we would
rather serve the request un-throttled than turn a cache outage into an API
outage, so a cache error counts as "allowed".
"""

import logging

from rest_framework import throttling

logger = logging.getLogger(__name__)


class FailOpenMixin:
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.warning("rate limiter unavailable, allowing request", exc_info=True)
            return True


class AnonRateThrottle(FailOpenMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(FailOpenMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(FailOpenMixin, throttling.ScopedRateThrottle):
    pass
