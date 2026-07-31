"""Area configuration: where to build the road network graph.

The routing core and graph layer must never hardcode a place — Verona is
only the default. Any OSM place name or bounding box works.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AreaConfig:
    """Defines the OSM extract to route on.

    Exactly one of `place` or `bbox` must be set. `bbox` is
    `(west, south, east, north)` in WGS84 degrees — the `(left, bottom,
    right, top)` convention osmnx's `graph_from_bbox` expects.
    """

    place: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    network_type: str = "drive"

    def __post_init__(self) -> None:
        if (self.place is None) == (self.bbox is None):
            raise ValueError("Exactly one of `place` or `bbox` must be set.")


def verona() -> AreaConfig:
    """Default project area: Verona, Italy."""
    return AreaConfig(place="Verona, Italy")
