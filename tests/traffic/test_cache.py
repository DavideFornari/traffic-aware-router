"""Unit tests for the TTL probe cache."""

import time

from router.traffic.cache import TrafficCache


def test_miss_on_empty_cache():
    cache = TrafficCache[str]()
    assert cache.get(0.0, 0.0) is None


def test_set_then_get_within_ttl():
    cache = TrafficCache[str](ttl_s=60.0)
    cache.set(100.0, 200.0, "value")
    assert cache.get(100.0, 200.0) == "value"


def test_nearby_points_within_the_same_grid_cell_hit():
    cache = TrafficCache[str](grid_m=50.0)
    cache.set(100.0, 100.0, "value")
    # 10m away, same 50m grid cell
    assert cache.get(105.0, 103.0) == "value"


def test_points_in_different_grid_cells_miss():
    cache = TrafficCache[str](grid_m=50.0)
    cache.set(0.0, 0.0, "value")
    assert cache.get(1000.0, 1000.0) is None


def test_expired_entry_is_a_miss():
    cache = TrafficCache[str](ttl_s=0.01)
    cache.set(0.0, 0.0, "value")
    time.sleep(0.05)
    assert cache.get(0.0, 0.0) is None


def test_expired_entry_is_removed_from_the_store():
    cache = TrafficCache[str](ttl_s=0.01)
    cache.set(0.0, 0.0, "value")
    time.sleep(0.05)
    cache.get(0.0, 0.0)
    assert len(cache) == 0
