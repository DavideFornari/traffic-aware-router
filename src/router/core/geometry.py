"""Great-circle distance, used by the A* heuristic.

Pure math, no shapely/pyproj: the core stays arrays-only and independent of
the graph layer's geometry stack.
"""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def great_circle_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))
