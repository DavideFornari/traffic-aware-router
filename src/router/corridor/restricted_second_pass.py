"""Second pass with turn restrictions: line-graph routing on a corridor.

Ties `build_corridor`'s output, `apply_traffic`'s adjusted weights, and
`resolve_restrictions`'s output into one call: builds a small line graph
from just the corridor's edges — not the whole city's, which the two-pass
design exists specifically to avoid — and routes on it via
`route_on_line_graph`, so turn restrictions and turn penalties are
respected on the traffic-aware second pass.

Deliberately scoped to the second pass only (CLAUDE.md's improvement
backlog #1): the free-flow first pass that bounds the corridor stays on
the plain node graph, since turn-restriction-aware routing is strictly
more expensive and the first pass only needs to be a cheap, reasonable
bound — not the final answer.
"""

from __future__ import annotations

import networkx as nx
import numpy as np

from router.corridor.subgraph import Subgraph
from router.graph.line_graph import build_line_graph, route_on_line_graph
from router.graph.restrictions import TurnRestriction


def corridor_line_graph(
    corridor: Subgraph,
    real_node_ids: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    restrictions: list[TurnRestriction] | None = None,
) -> nx.MultiDiGraph:
    """Build a small `networkx` graph from a corridor, ready for `build_line_graph`.

    `corridor` must carry `edge_keys` (pass `edge_keys=csr.edge_keys` to
    `build_corridor`). `real_node_ids`/`lat`/`lon`/`x`/`y` are
    corridor-local arrays — index `i` is corridor node `i`, already indexed
    by `corridor.sub_to_full` — the same convention `apply_traffic` uses
    for its own `x`/`y`. `weights`, aligned with `corridor.indices`, is
    what becomes each edge's `travel_time`: pass `corridor.weights` for
    free-flow, or a `TrafficResult.adjusted_weights` for the traffic-aware
    second pass.
    """
    if corridor.edge_keys is None:
        raise ValueError(
            "corridor.edge_keys is required; pass edge_keys=csr.edge_keys to build_corridor()."
        )

    real_graph = nx.MultiDiGraph()
    for i, real_id in enumerate(real_node_ids):
        real_graph.add_node(
            int(real_id), lat=float(lat[i]), lon=float(lon[i]), x=float(x[i]), y=float(y[i])
        )
    for pos, (u, v, key) in enumerate(corridor.edge_keys):
        real_graph.add_edge(u, v, key=key, travel_time=float(weights[pos]))

    return build_line_graph(real_graph, restrictions=restrictions, weight="travel_time")


def route_corridor_second_pass(
    corridor: Subgraph,
    real_node_ids: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    origin_real_node: int,
    destination_real_node: int,
    restrictions: list[TurnRestriction] | None = None,
) -> tuple[list[int], float] | None:
    """Turn-restriction-aware route between two real nodes, on the corridor.

    Convenience wrapper around `corridor_line_graph` + `route_on_line_graph`.
    Returns `(real_node_path, total_cost)`, or `None` if unreachable — e.g.
    every route between the two nodes is blocked by a restriction, which a
    plain node-graph Dijkstra on the same corridor would never report.
    """
    line_graph = corridor_line_graph(corridor, real_node_ids, lat, lon, x, y, weights, restrictions)
    return route_on_line_graph(line_graph, origin_real_node, destination_real_node)
