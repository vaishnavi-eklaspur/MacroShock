"""Redis caching layer with graceful degradation.

Expensive analytics (covariance-based risk, factor regression, reverse-stress solves) are
pure functions of their inputs, so results are cached under a deterministic key derived from
(endpoint, weights, scenario, confidence, ...). If Redis is unavailable the app logs a
warning and computes directly - it never fails because of the cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger("macroshock.cache")

try:  # redis is optional at runtime
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None  # type: ignore


class Cache:
    def __init__(self, url: str | None = None, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._client = None
        self._enabled = False
        url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        if redis is None:
            logger.warning("redis package not installed; caching disabled.")
            return
        try:
            self._client = redis.Redis.from_url(url, socket_connect_timeout=1,
                                                socket_timeout=1, decode_responses=True)
            self._client.ping()
            self._enabled = True
            logger.info("Connected to Redis at %s", url)
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Redis unavailable (%s); caching disabled, computing directly.", exc)
            self._client = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def make_key(prefix: str, payload: dict[str, Any]) -> str:
        """Deterministic key: stable JSON of the payload, hashed."""
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=float)
        digest = hashlib.sha256(blob.encode()).hexdigest()[:32]
        return f"macroshock:{prefix}:{digest}"

    def get_or_compute(self, prefix: str, payload: dict[str, Any],
                       compute: Callable[[], dict]) -> tuple[dict, bool]:
        """Return (result, cache_hit). Falls back to compute() on any cache error."""
        if not self._enabled:
            return compute(), False

        key = self.make_key(prefix, payload)
        try:
            cached = self._client.get(key)  # type: ignore[union-attr]
            if cached is not None:
                return json.loads(cached), True
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache read failed (%s); computing directly.", exc)
            return compute(), False

        result = compute()
        try:
            self._client.setex(key, self.ttl, json.dumps(result, default=float))  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache write failed (%s).", exc)
        return result, False
