"""Corridor extraction: first-pass Dijkstra, ellipse bound, Yen, buffer union.

Implements the "corridor" step of CLAUDE.md's two-pass design: a full-graph
static Dijkstra bounds the ellipse, Yen then runs only on the (much
smaller) ellipse subgraph, and the buffered union of its k paths is folded
back in to catch structurally different alternatives. The result is a
corridor subgraph, small enough for per-query traffic sampling (Milestone
5) and a traffic-aware second pass — never the full city graph again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry.base import BaseGeometry

from router.core.dijkstra import dijkstra
from router.core.yen import yen_k_shortest_paths
from router.corridor.buffer import buffered_path_union, nodes_in_polygon
from router.corridor.ellipse import ellipse_l_max, in_ellipse
from router.corridor.subgraph import Subgraph, extract_subgraph

DEFAULT_EPSILON = 0.3
DEFAULT_K = 4
DEFAULT_BUFFER_M = 200.0


@dataclass(frozen=True)
class CorridorResult:
    """Output of `build_corridor`.

    `subgraph` is the final corridor (ellipse union buffer), with node
    indices relative to the full graph reachable via `subgraph.sub_to_full`.
    `candidate_paths` are Yen's k paths on the ellipse subgraph, as
    full-graph node index lists, cheapest first, matching `candidate_costs`.
    `ellipse_mask` and `buffer_polygon` (both in the same projected CRS as
    the `x`/`y` passed to `build_corridor`) are exposed for debugging/
    visualisation — e.g. `scripts/debug_corridor.py` — not needed for
    routing itself.
    """

    subgraph: Subgraph
    t_star: float
    l_max: float
    candidate_paths: list[list[int]]
    candidate_costs: list[float]
    ellipse_mask: np.ndarray
    buffer_polygon: BaseGeometry | None


def build_corridor(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    origin: int,
    destination: int,
    v_max: float,
    epsilon: float = DEFAULT_EPSILON,
    k: int = DEFAULT_K,
    buffer_m: float = DEFAULT_BUFFER_M,
) -> CorridorResult:
    """Build the traffic-sampling corridor between `origin` and `destination`.

    `x`/`y` must be projected metres (see `router.graph.csr.CSRGraph`'s
    docstring); `v_max` must be in the same distance/time units as
    `weights` (metres and seconds, for OSM travel times).
    """
    first_pass = dijkstra(indptr, indices, weights, source=origin, target=destination)
    t_star = float(first_pass.dist[destination])
    if math.isinf(t_star):
        raise ValueError("No path exists between origin and destination.")

    l_max = ellipse_l_max(t_star, epsilon, v_max)
    ellipse_mask = in_ellipse(x, y, (x[origin], y[origin]), (x[destination], y[destination]), l_max)
    ellipse_mask[origin] = True
    ellipse_mask[destination] = True

    ellipse_sub = extract_subgraph(indptr, indices, weights, ellipse_mask)
    sub_origin = int(ellipse_sub.full_to_sub[origin])
    sub_destination = int(ellipse_sub.full_to_sub[destination])

    yen_paths = yen_k_shortest_paths(
        ellipse_sub.indptr,
        ellipse_sub.indices,
        ellipse_sub.weights,
        sub_origin,
        sub_destination,
        k=k,
    )
    candidate_paths = [[int(ellipse_sub.sub_to_full[i]) for i in path] for path, _ in yen_paths]
    candidate_costs = [cost for _, cost in yen_paths]

    polygon = buffered_path_union(candidate_paths, x, y, buffer_m)
    buffer_mask = nodes_in_polygon(x, y, polygon)

    corridor_mask = ellipse_mask | buffer_mask
    corridor_sub = extract_subgraph(indptr, indices, weights, corridor_mask)

    return CorridorResult(
        subgraph=corridor_sub,
        t_star=t_star,
        l_max=l_max,
        candidate_paths=candidate_paths,
        candidate_costs=candidate_costs,
        ellipse_mask=ellipse_mask,
        buffer_polygon=polygon,
    )
