"""Pure helper functions for the Streamlit UI.

Kept separate from app/main.py so they're unit-testable without a running
Streamlit/browser session — everything that touches `st.*` or `folium.*`
directly stays in main.py instead.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import osmnx as ox

from router.core.dijkstra import dijkstra
from router.core.geometry import great_circle_distance_m
from router.traffic.pipeline import TrafficResult


def nearest_node(lat: np.ndarray, lon: np.ndarray, point: tuple[float, float]) -> int:
    """Index of the graph node closest to `point` (lat, lon), by great-circle distance.

    Snaps to the nearest *intersection*, which can be a poor proxy for "the
    road this address is actually on" for a point in the middle of a long
    block — see `nearest_edge_endpoints` for the address/click/paste case,
    where that distinction matters. Kept for callers (debug/benchmark
    scripts) that just need a quick, good-enough node for a fixed point.
    """
    distances = [
        great_circle_distance_m(lat[i], lon[i], point[0], point[1]) for i in range(len(lat))
    ]
    return int(np.argmin(distances))


def nearest_edge_endpoints(graph: nx.MultiDiGraph, x: float, y: float) -> tuple[int, int]:
    """The `(u, v)` endpoint node ids of the edge nearest `(x, y)`.

    `(x, y)` must be in `graph`'s own CRS (projected metres, for a
    `prepare_graph`d graph — see `CSRGraph`'s docstring on why). Unlike
    `nearest_node`, this finds the road the point actually sits on (osmnx's
    `nearest_edges`, R-tree backed, using the edge's true geometry when the
    graph has it) rather than guessing by which intersection happens to be
    closest — the two frequently disagree for a point mid-block, which is
    exactly the "wrong starting point for a typed address" bug this fixes.
    Both `u` and `v` are returned as candidates; which one actually gives
    the better *route* is a routing question, not a geometry one — see
    `select_best_endpoints`.
    """
    u, v, _key = ox.distance.nearest_edges(graph, x, y)
    return u, v


def select_best_endpoints(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    origin_candidates: tuple[int, int],
    destination_candidates: tuple[int, int],
) -> tuple[int, int]:
    """Pick whichever origin/destination candidate pair gives the cheapest route.

    `nearest_edge_endpoints` gives two plausible nodes on each end (the
    queried point could be closer to either end of its nearest edge, and
    the *closer* one isn't always the one that leads to the *faster*
    route — a one-way street or a slower local road can make the farther
    node the better choice). Checks all four combinations of the up-to-two
    origin candidates and up-to-two destination candidates, using only two
    full-graph Dijkstra runs (one per origin candidate; each with no
    target computes distances to every node at once, covering both
    destination candidates in the same pass) rather than up to four.
    """
    origins = list(dict.fromkeys(origin_candidates))
    destinations = list(dict.fromkeys(destination_candidates))

    best_origin, best_destination, best_cost = origins[0], destinations[0], float("inf")
    for origin in origins:
        result = dijkstra(indptr, indices, weights, source=origin)
        for destination in destinations:
            cost = float(result.dist[destination])
            if cost < best_cost:
                best_origin, best_destination, best_cost = origin, destination, cost

    return best_origin, best_destination


def path_to_latlon(path: list[int], lat: np.ndarray, lon: np.ndarray) -> list[tuple[float, float]]:
    """A node-index path as a list of `(lat, lon)` points, for folium."""
    return [(float(lat[i]), float(lon[i])) for i in path]


def format_duration(seconds: float) -> str:
    """Human-readable duration: `"45 s"` or `"12 min 30 s"`."""
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs:02d} s"


def format_delta(delta_seconds: float) -> str:
    """Signed human-readable duration delta: `"+2 min 10 s"` or `"-30 s"`."""
    sign = "+" if delta_seconds >= 0 else "-"
    return f"{sign}{format_duration(abs(delta_seconds))}"


def traffic_summary(traffic: TrafficResult) -> str:
    """One-line status of a completed `apply_traffic` call, for the UI."""
    if traffic.probes_queried == 0:
        return "No TomTom API key set — showing free-flow routing only."
    if not traffic.traffic_available:
        return (
            f"Queried {traffic.probes_queried} probes, but none matched a corridor edge — "
            "showing free-flow routing only."
        )
    return f"Live traffic matched {traffic.probes_matched} of {traffic.probes_queried} probes."


def source_node_of_position(indptr: np.ndarray, position: int) -> int:
    """The CSR source-node index whose out-edge range contains `position`."""
    return int(np.searchsorted(indptr, position, side="right") - 1)


def parse_latlon(text: str) -> tuple[float, float] | None:
    """Parse `"lat, lon"` text input, or `None` if it isn't valid."""
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (lat, lon)
