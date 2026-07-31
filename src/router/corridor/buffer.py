"""Buffer the union of Yen's k candidate paths to widen the corridor.

A structurally different alternative (e.g. a parallel street one block
over) can fall just outside the ellipse bound. Buffering the union of the k
shortest paths and folding whatever it covers into the corridor recovers
such alternatives without re-running Yen on a wider ellipse (see CLAUDE.md's
corridor design).
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def buffered_path_union(
    paths: list[list[int]], x: np.ndarray, y: np.ndarray, buffer_m: float
) -> BaseGeometry | None:
    """Polygon: the union of `paths` (full-graph node indices) buffered by `buffer_m` metres.

    `x`/`y` must be projected metric coordinates aligned with those node
    indices, so that `buffer_m` is metres, not degrees. Returns `None` if no
    path has at least two nodes (nothing to buffer).
    """
    lines = [LineString([(x[i], y[i]) for i in path]) for path in paths if len(path) >= 2]
    if not lines:
        return None
    return unary_union(lines).buffer(buffer_m)


def nodes_in_polygon(x: np.ndarray, y: np.ndarray, polygon: BaseGeometry | None) -> np.ndarray:
    """Boolean mask of which `(x, y)` points fall inside `polygon`.

    Vectorised via `shapely.contains_xy` — a per-node Python loop would be
    the dominant cost at city scale (~10^5 nodes) otherwise.
    """
    if polygon is None:
        return np.zeros(len(x), dtype=bool)
    return shapely.contains_xy(polygon, x, y)
