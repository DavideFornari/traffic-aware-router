"""Pure helper functions for the Streamlit UI.

Kept separate from app/main.py so they're unit-testable without a running
Streamlit/browser session — everything that touches `st.*` or `folium.*`
directly stays in main.py instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.ops import substring

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


@dataclass(frozen=True)
class EdgeSnap:
    """The edge nearest a query point, and everything needed to route from
    it and to draw the approach segment connecting the query point to
    wherever routing actually starts.

    `geometry` and `distance_from_u` are in the same projected CRS as the
    `(x, y)` passed to `nearest_edge_endpoints`.
    """

    u: int
    v: int
    approach_to_u: float
    approach_to_v: float
    geometry: LineString
    distance_from_u: float

    @property
    def candidates(self) -> tuple[tuple[int, float], tuple[int, float]]:
        """`((u, approach_to_u), (v, approach_to_v))`, ready for `select_best_endpoints`."""
        return (self.u, self.approach_to_u), (self.v, self.approach_to_v)

    def connector_coords(self, chosen_node: int) -> list[tuple[float, float]]:
        """Projected `(x, y)` points from the query point to `chosen_node`,
        following the edge's own geometry rather than a straight line —
        important for a long merged edge (e.g. one that crosses a bridge),
        where a straight line from the query point to a distant endpoint
        could cut across whatever the edge actually goes around. Ordered
        query-point-first, `chosen_node`-last. `chosen_node` must be this
        snap's `u` or `v`.
        """
        if chosen_node == self.v:
            sub = substring(self.geometry, self.distance_from_u, self.geometry.length)
            return list(sub.coords)
        if chosen_node == self.u:
            sub = substring(self.geometry, 0, self.distance_from_u)
            coords = list(sub.coords)
            coords.reverse()
            return coords
        raise ValueError(f"node {chosen_node} is not an endpoint of this edge snap")


def nearest_edge_endpoints(graph: nx.MultiDiGraph, x: float, y: float) -> EdgeSnap:
    """The edge nearest `(x, y)`, as an `EdgeSnap`.

    `(x, y)` must be in `graph`'s own CRS (projected metres, for a
    `prepare_graph`d graph — see `CSRGraph`'s docstring on why). Unlike
    `nearest_node`, this finds the road the point actually sits on (osmnx's
    `nearest_edges`, R-tree backed, using the edge's true geometry when the
    graph has it) rather than guessing by which intersection happens to be
    closest.

    osmnx collapses any chain of degree-2 nodes (real intersections only
    become graph nodes where 3+ ways meet) into a single edge, regardless
    of length or of the street name changing partway through — a merged
    edge can run hundreds of metres, e.g. a street that continues across a
    bridge under a different name. When that happens, *both* endpoints can
    be far from the query point, in different directions, and assuming the
    point is "basically at" one of them is exactly wrong. The returned
    approach time — the query point projected onto the edge's own geometry
    (its true shape, when osmnx recorded one, else a straight line between
    the endpoints), with the edge's travel time split proportionally at
    that point — is what lets `select_best_endpoints` weigh "how far is it
    to actually reach this candidate" against "how good is the route once
    there", instead of assuming free teleportation to whichever candidate
    happens to have the cheaper onward route.
    """
    u, v, key = ox.distance.nearest_edges(graph, x, y)
    data = graph.get_edge_data(u, v, key)

    geometry = data.get("geometry")
    if geometry is None:
        geometry = LineString(
            [
                (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                (graph.nodes[v]["x"], graph.nodes[v]["y"]),
            ]
        )

    total_length = geometry.length
    distance_from_u = geometry.project(Point(x, y))
    fraction_from_u = distance_from_u / total_length if total_length > 0 else 0.5

    travel_time = float(data["travel_time"])
    approach_to_u = travel_time * fraction_from_u
    approach_to_v = travel_time * (1.0 - fraction_from_u)

    return EdgeSnap(
        u=u,
        v=v,
        approach_to_u=approach_to_u,
        approach_to_v=approach_to_v,
        geometry=geometry,
        distance_from_u=distance_from_u,
    )


def select_best_endpoints(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    origin_candidates: tuple[tuple[int, float], tuple[int, float]],
    destination_candidates: tuple[tuple[int, float], tuple[int, float]],
) -> tuple[int, int]:
    """Pick whichever origin/destination candidate pair gives the cheapest total trip.

    Each candidate is `(node, approach_cost)` from `nearest_edge_endpoints`
    — `approach_cost` estimates the time to actually reach that node from
    the true queried point, so a long merged edge's two endpoints are
    compared on *total* cost (approach + route + approach), not assumed
    equally reachable. The closer candidate isn't always the better one
    even so — a one-way street or a slower local road can make the
    farther-to-reach node the better overall choice — so all four
    combinations of the up-to-two origin and up-to-two destination
    candidates are checked, using only two full-graph Dijkstra runs (one
    per origin candidate; each with no target computes distances to every
    node at once, covering both destination candidates per run) rather
    than four.
    """
    best_origin, best_destination = origin_candidates[0][0], destination_candidates[0][0]
    best_cost = float("inf")
    for origin, origin_approach in origin_candidates:
        result = dijkstra(indptr, indices, weights, source=origin)
        for destination, destination_approach in destination_candidates:
            cost = origin_approach + float(result.dist[destination]) + destination_approach
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


@dataclass(frozen=True)
class MapClickResult:
    """The effect of one map-click event on the origin/destination pick state."""

    origin: tuple[float, float]
    destination: tuple[float, float]
    last_map_click: tuple[float, float] | None
    pick_mode: str | None


def apply_map_click(
    clicked: tuple[float, float] | None,
    last_map_click: tuple[float, float] | None,
    pick_mode: str | None,
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> MapClickResult:
    """Fold one map click into the origin/destination "pick mode" state.

    `pick_mode` is `"Origin"`, `"Destination"`, or `None` (inactive — the
    map can be freely panned/zoomed without changing either point).
    Picking is one-use: a click while a mode is active applies it and
    returns `pick_mode=None`, so the caller's next render shows the pick
    button back in its inactive state, per the UX being provided (activate
    a pick, click the map once, done).

    `streamlit-folium` keeps returning the same last-clicked point on every
    rerun until the map is clicked again, so `clicked` is compared against
    `last_map_click` and ignored if unchanged — otherwise activating a pick
    mode *without* clicking again would immediately (and wrongly) consume
    a stale click from earlier. This comparison happens whether or not a
    pick mode is active, so a click made while inactive is still marked
    "seen" and can't be replayed later once a mode is activated.
    """
    if clicked is None or clicked == last_map_click:
        return MapClickResult(origin, destination, last_map_click, pick_mode)

    if pick_mode == "Origin":
        return MapClickResult(clicked, destination, clicked, None)
    if pick_mode == "Destination":
        return MapClickResult(origin, clicked, clicked, None)
    return MapClickResult(origin, destination, clicked, pick_mode)
