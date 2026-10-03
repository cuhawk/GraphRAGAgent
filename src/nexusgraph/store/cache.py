"""Optional caches: in-process TTL cache (default) or Redis when configured.

Used for exact-match retrieval-result caching. A broken Redis degrades to a
warning and a miss - never to an error surfaced to the user.
"""

from __future__ import annotations

import time

from nexusgraph.observability.logging import get_logger

logger = get_logger("store.cache")


class InMemoryCache:
    def __init__(self, max_entries: int = 1_000) -> None:
        self._max = max_entries
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_s: float = 300.0) -> None:
        if len(self._store) >= self._max:
            # Drop the earliest entry (insertion-ordered dict).
            self._store.pop(next(iter(self._store)))
        self._store[key] = (time.monotonic() + ttl_s, value)


class RedisCache:
    def __init__(self, url: str, prefix: str = "nexusgraph:") -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True,
                                            socket_connect_timeout=2,
                                            socket_timeout=2)
        self._prefix = prefix

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(f"{self._prefix}{key}")
        except Exception as exc:
            logger.warning("redis get failed: %s", exc)
            return None

    def set(self, key: str, value: str, ttl_s: float = 300.0) -> None:
        try:
            self._client.set(f"{self._prefix}{key}", value, ex=max(1, int(ttl_s)))
        except Exception as exc:
            logger.warning("redis set failed: %s", exc)


def make_cache(redis_url: str | None) -> InMemoryCache | RedisCache:
    if redis_url:
        try:
            return RedisCache(redis_url)
        except Exception as exc:  # pragma: no cover - depends on env
            logger.warning("redis unavailable (%s); using in-memory cache", exc)
    return InMemoryCache()
