"""Match a TomTom flow segment polyline to the OSM edge it was queried for.

The fiddliest, least visible part of this project (see CLAUDE.md). TomTom
snaps a queried point to whatever road it thinks is nearest, which is not
necessarily *our* edge: two documented failure modes are the classic silent
ones —

- **Opposite-carriageway assignment.** A dual carriageway's two directions
  run a few metres apart; TomTom can snap to the wrong one, handing our
  edge the other direction's traffic. Buffered distance alone can't catch
  this (both carriageways are within a few metres), but *bearing* can: the
  wrong carriageway runs opposite (~180 degrees off), while position noise
  or minor snapping error stays within a few tens of degrees.
- **Vertically stacked roads.** Bridges/underpasses/ramps overlap in plan
  view; two roads at different elevations look identical in this 2D
  matching and neither buffer distance nor bearing can distinguish them.
  Not handled here — worth knowing this stays a source of mismatches.

Other documented error modes: a TomTom segment spanning several short OSM
edges, or several TomTom segments covering one long OSM edge, either of
which can leave a queried edge only partially represented by the match.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point

DEFAULT_BUFFER_M = 15.0
DEFAULT_MAX_BEARING_DIFF_DEG = 30.0


def bearing_deg(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass-style bearing (0-360, clockwise from the CRS's +y axis).

    Computed directly in the projected CRS, not from lat/lon: for a UTM
    zone, +y is (approximately) north and +x is east, so this is close
    enough to true compass bearing for a ~30-degree tolerance check
    without needing a geodesic bearing formula.
    """
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360.0


def bearing_difference_deg(bearing1: float, bearing2: float) -> float:
    """Smallest angle (0-180) between two bearings."""
    diff = abs(bearing1 - bearing2) % 360.0
    return min(diff, 360.0 - diff)


def local_bearing_deg(
    segment_coords_xy: list[tuple[float, float]], point_x: float, point_y: float
) -> float:
    """Bearing of `segment_coords_xy`'s local direction nearest `(point_x, point_y)`.

    A TomTom segment can be long and curved; its overall start-to-end
    bearing can differ sharply from its direction at the point actually
    being matched (e.g. a segment that bends around a corner well past the
    queried edge). `line.project` finds how far along the polyline the
    closest point to `(point_x, point_y)` is; walking the cumulative vertex
    distances to find which pair of vertices that falls between and using
    just that pair's bearing gives the segment's *local* direction there,
    which is what should be compared to the edge's own bearing.
    """
    line = LineString(segment_coords_xy)
    target_distance = line.project(Point(point_x, point_y))

    cumulative = 0.0
    last = len(segment_coords_xy) - 2
    for i in range(last + 1):
        x1, y1 = segment_coords_xy[i]
        x2, y2 = segment_coords_xy[i + 1]
        cumulative += math.hypot(x2 - x1, y2 - y1)
        if cumulative >= target_distance or i == last:
            return bearing_deg(x1, y1, x2, y2)

    raise AssertionError("unreachable: the loop above always returns by i == last")


def edge_matches_segment(
    edge_x1: float,
    edge_y1: float,
    edge_x2: float,
    edge_y2: float,
    segment_coords_xy: list[tuple[float, float]],
    buffer_m: float = DEFAULT_BUFFER_M,
    max_bearing_diff_deg: float = DEFAULT_MAX_BEARING_DIFF_DEG,
) -> bool:
    """Is `segment_coords_xy` (projected) a plausible match for this edge?

    Two checks, both required: the edge's midpoint must fall within
    `buffer_m` of the segment polyline (geometric overlap), and the edge's
    bearing must be within `max_bearing_diff_deg` of the segment's *local*
    bearing at the point nearest the edge's midpoint (direction check — see
    module docstring for why this matters, and `local_bearing_deg` for why
    it's the local bearing and not the segment's overall one).
    """
    if len(segment_coords_xy) < 2:
        return False

    segment_line = LineString(segment_coords_xy)
    edge_mid_x, edge_mid_y = (edge_x1 + edge_x2) / 2, (edge_y1 + edge_y2) / 2
    edge_mid = Point(edge_mid_x, edge_mid_y)
    if segment_line.distance(edge_mid) > buffer_m:
        return False

    edge_bearing = bearing_deg(edge_x1, edge_y1, edge_x2, edge_y2)
    segment_bearing = local_bearing_deg(segment_coords_xy, edge_mid_x, edge_mid_y)

    return bearing_difference_deg(edge_bearing, segment_bearing) <= max_bearing_diff_deg
