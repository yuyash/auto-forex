"""DRF throttles that tolerate temporary Redis cache failures."""

from __future__ import annotations

import logging
from typing import Any

from redis.exceptions import RedisError
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class RedisCacheFailOpenThrottleMixin:
    """Allow requests when throttle state cannot be read from Redis."""

    def allow_request(self, request: Any, view: Any) -> bool:
        """Run the normal throttle check, failing open on Redis connectivity errors."""
        try:
            return super().allow_request(request, view)  # type: ignore[misc]
        except RedisError:
            scope = getattr(self, "scope", None) or self.__class__.__name__
            logger.exception(
                "DRF throttle cache unavailable; allowing request (scope=%s)",
                scope,
            )
            return True


class ResilientUserRateThrottle(RedisCacheFailOpenThrottleMixin, UserRateThrottle):
    """User throttle that does not fail API requests when Redis is saturated."""


class ResilientAnonRateThrottle(RedisCacheFailOpenThrottleMixin, AnonRateThrottle):
    """Anonymous throttle that does not fail API requests when Redis is saturated."""
