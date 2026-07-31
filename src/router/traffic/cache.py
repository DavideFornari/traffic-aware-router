"""TTL cache for TomTom probe responses, keyed by quantised coordinates.

Nearby repeated queries (e.g. two overlapping corridors, or re-running the
same query) reuse a cached response instead of spending quota. Keys are
projected metric coordinates (not lat/lon) quantised to a `grid_m` grid —
so two probe points within the same grid cell are treated as one probe,
independent of latitude-dependent degree-to-metre distortion.
"""

from __future__ import annotations

import time

DEFAULT_TTL_S = 300.0
DEFAULT_GRID_M = 50.0


class TrafficCache[T]:
    """A simple TTL cache keyed by `(x, y)` quantised to `grid_m` metres."""

    def __init__(self, ttl_s: float = DEFAULT_TTL_S, grid_m: float = DEFAULT_GRID_M) -> None:
        self.ttl_s = ttl_s
        self.grid_m = grid_m
        self._store: dict[tuple[int, int], tuple[T, float]] = {}

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (round(x / self.grid_m), round(y / self.grid_m))

    def get(self, x: float, y: float) -> T | None:
        entry = self._store.get(self._key(x, y))
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            del self._store[self._key(x, y)]
            return None
        return value

    def set(self, x: float, y: float, value: T) -> None:
        self._store[self._key(x, y)] = (value, time.monotonic() + self.ttl_s)

    def __len__(self) -> int:
        return len(self._store)
