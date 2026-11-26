"""Thread-safe in-memory TTL cache with LRU eviction.

The cache is intentionally dependency-free: it is good enough for a single
instance and keeps the CI/demo experience simple. The small interface makes it
easy to swap in Redis later (the service depends on the interface, not the
class).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple


def build_cache_key(*parts: object, namespace: str = "docqa") -> str:
    """Build a stable SHA-256 cache key from arbitrary parts."""
    hasher = hashlib.sha256()
    hasher.update(namespace.encode("utf-8"))
    for part in parts:
        hasher.update(b"\x1f")
        hasher.update(str(part).encode("utf-8"))
    return hasher.hexdigest()


class TTLCache:
    """Simple TTL + LRU cache.

    ``clock`` is injectable to make TTL behaviour deterministic in tests.
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        self._data: OrderedDict[str, Tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._expired = 0
        self._evictions = 0

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """Return a cached value or ``None`` (counts hit/miss/expiration)."""
        now = self._clock()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None
            expires_at, value = item
            if expires_at <= now:
                del self._data[key]
                self._expired += 1
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        now = self._clock()
        with self._lock:
            self._data[key] = (now + self._ttl_seconds, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)
                self._evictions += 1

    def purge_expired(self) -> int:
        """Remove expired entries, return how many were removed."""
        now = self._clock()
        removed = 0
        with self._lock:
            for key in [key for key, (exp, _) in self._data.items() if exp <= now]:
                del self._data[key]
                removed += 1
            self._expired += removed
        return removed

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = self._misses = self._expired = self._evictions = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            hits, misses = self._hits, self._misses
            total = hits + misses
            return {
                "size": len(self._data),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total, 4) if total else 0.0,
                "expired": self._expired,
                "evictions": self._evictions,
            }
