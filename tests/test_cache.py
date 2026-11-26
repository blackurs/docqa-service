from __future__ import annotations

import pytest

from docqa.core.cache import TTLCache, build_cache_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_set_and_get() -> None:
    cache = TTLCache(ttl_seconds=60, clock=FakeClock())
    cache.set("k", {"answer": 42})
    assert cache.get("k") == {"answer": 42}
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 0


def test_miss_counts() -> None:
    cache = TTLCache(ttl_seconds=60)
    assert cache.get("missing") is None
    assert cache.stats()["misses"] == 1


def test_entry_expires_after_ttl() -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    cache.set("k", "value")

    clock.now = 9.9
    assert cache.get("k") == "value"

    clock.now = 10.1
    assert cache.get("k") is None
    assert cache.stats()["expired"] == 1
    assert cache.stats()["size"] == 0


def test_purge_expired() -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=5, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    clock.now = 10
    assert cache.purge_expired() == 2
    assert cache.stats()["size"] == 0
    assert cache.get("a") is None


def test_lru_eviction() -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, max_entries=2, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # make "b" the least recently used
    cache.set("c", 3)

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3
    assert cache.stats()["evictions"] == 1


def test_stats_hit_rate() -> None:
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", 1)
    cache.get("k")
    cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_cache_key_is_stable_and_sensitive_to_inputs() -> None:
    key_a = build_cache_key("q", "context", 4)
    key_b = build_cache_key("q", "context", 4)
    key_c = build_cache_key("q", "context", 5)
    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64


def test_invalid_parameters_rejected() -> None:
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=10, max_entries=0)
