"""Line-graph adapter: turn restrictions and turn penalties.

Each line-graph node is a directed real-graph edge; each line-graph edge
(an "arc") is a maneuver from one real edge to the next through the node
they share. A banned turn is simply an absent arc; a turn penalty is extra
cost on an arc. The routing core is completely unchanged by this — Dijkstra
and A* still just consume CSR arrays, built here (via the existing
`build_csr`) from this line graph instead of from the node graph.

Call `build_line_graph` on an already-`prepare_graph`d graph (needs
`travel_time`, and `lat`/`lon`/`x`/`y` on every node), exactly like
`build_csr`.

Cost accounting: an arc from real edge A to real edge B costs B's own
travel time (the cost of *entering* B) — the source edge of a route is
never entered via an arc, so a line-graph Dijkstra/A* distance is the true
route cost *minus* the source edge's own travel time. `source_edge_weight`
gives that missing amount back, for a total comparable to a node-graph
Dijkstra between the same two real nodes.
"""

from __future__ import annotations

import math

import networkx as nx
import numpy as np

from router.core.dijkstra import dijkstra, reconstruct_path
from router.graph.csr import build_csr
from router.graph.restrictions import TurnRestriction

EdgeKey = tuple[int, int, int]

DEFAULT_U_TURN_PENALTY_S = 0.0


def build_line_graph(
    graph: nx.MultiDiGraph,
    restrictions: list[TurnRestriction] | None = None,
    weight: str = "travel_time",
    u_turn_penalty_s: float = DEFAULT_U_TURN_PENALTY_S,
) -> nx.MultiDiGraph:
    """Build the line graph: nodes are directed real edges, arcs are turns.

    Each line-graph node keeps its real edge's *head* node's coordinates as
    `lat`/`lon`/`x`/`y` (plus `edge_key`, the originating `(u, v, key)`, and
    `weight`, that edge's own travel time) — not the tail, and not a
    midpoint. That's where you physically are once you've finished
    traversing the edge, which is exactly the point the A* heuristic must
    be anchored at to stay admissible: the remaining cost from wherever the
    search currently stands can't be less than the straight-line distance
    from *there* to the destination divided by `v_max`.

    `no_*` restrictions remove the specific `(from_edge, to_edge)` arc at
    their via node; `only_*` restrictions remove every *other* arc leaving
    that via node for the given `from_edge`. Restriction types this project
    doesn't otherwise recognise are ignored (an unenforced restriction is
    at least never a silently *wrong* route, only a permissive one).
    """
    restrictions = restrictions or []
    banned: set[tuple[EdgeKey, int, EdgeKey]] = set()
    only_allowed: dict[tuple[EdgeKey, int], EdgeKey] = {}
    for r in restrictions:
        if r.restriction_type.startswith("no_"):
            banned.add((r.from_edge, r.via_node, r.to_edge))
        elif r.restriction_type.startswith("only_"):
            only_allowed[(r.from_edge, r.via_node)] = r.to_edge

    edge_keys: list[EdgeKey] = list(graph.edges(keys=True))
    node_id_of: dict[EdgeKey, int] = {ek: i for i, ek in enumerate(edge_keys)}

    out_edges_by_tail: dict[int, list[EdgeKey]] = {}
    for ek in edge_keys:
        out_edges_by_tail.setdefault(ek[0], []).append(ek)

    line_graph = nx.MultiDiGraph()
    line_graph.graph["edge_key_to_node"] = node_id_of

    for ek, node_id in node_id_of.items():
        u, v, k = ek
        head = graph.nodes[v]
        line_graph.add_node(
            node_id,
            edge_key=ek,
            weight=float(graph.edges[u, v, k][weight]),
            lat=head["lat"],
            lon=head["lon"],
            x=head["x"],
            y=head["y"],
        )

    for from_ek in edge_keys:
        via = from_ek[1]
        allowed_to = only_allowed.get((from_ek, via))
        for to_ek in out_edges_by_tail.get(via, []):
            if allowed_to is not None and to_ek != allowed_to:
                continue
            if (from_ek, via, to_ek) in banned:
                continue

            arc_weight = float(graph.edges[to_ek[0], to_ek[1], to_ek[2]][weight])
            if to_ek[1] == from_ek[0]:
                # Back where `from_ek` started: a literal U-turn.
                arc_weight += u_turn_penalty_s

            line_graph.add_edge(node_id_of[from_ek], node_id_of[to_ek], key=0, weight=arc_weight)

    return line_graph


def find_line_node(line_graph: nx.MultiDiGraph, edge_key: EdgeKey) -> int | None:
    """The line-graph node id for real edge `edge_key`, or `None` if absent."""
    return line_graph.graph["edge_key_to_node"].get(edge_key)


def source_edge_weight(line_graph: nx.MultiDiGraph, source_node_id: int) -> float:
    """The source real edge's own travel time (see module docstring)."""
    return line_graph.nodes[source_node_id]["weight"]


def route_on_line_graph(
    line_graph: nx.MultiDiGraph,
    origin_real_node: int,
    destination_real_node: int,
    weight: str = "weight",
) -> tuple[list[int], float] | None:
    """Shortest real-node route on a line graph, respecting whatever
    restrictions/penalties `build_line_graph` already baked into its arcs.

    A line graph has no notion of "the origin node" or "the destination
    node" — only directed real edges. Routing point-to-point therefore
    means: any edge leaving `origin_real_node` is a valid first move, and
    any edge arriving at `destination_real_node` is a valid last move: a
    multi-source, multi-target search over the candidates on both ends.

    Implemented with a single ordinary (single-source) Dijkstra run on the
    existing, unmodified core: a virtual super-source node is appended to
    the line graph's CSR arrays, with an edge to every candidate first-move
    line-node weighted by *that edge's own travel time* — which is exactly
    what `source_edge_weight` would otherwise need adding back afterwards
    (see the module docstring's "cost accounting" note), so here it's baked
    into the search instead. `target=None` runs Dijkstra to completion, and
    the best of every candidate last-move line-node's distance is the
    answer — no separate super-sink needed, since CSR rows are only cheap
    to extend by *appending* a new one, not by inserting an edge into an
    existing node's row.

    Returns `(real_node_path, total_cost)`, or `None` if unreachable.
    """
    csr = build_csr(line_graph, weight=weight)
    m = csr.n_nodes
    # `build_line_graph` assigns node ids 0..m-1 by construction, and
    # `build_csr` sorts node ids — so for this specific graph shape the CSR
    # index of a line-graph node always equals the node's own id. Asserted
    # here because `route_on_line_graph` silently gives wrong answers if
    # that ever stops holding (e.g. if `build_line_graph` starts skipping
    # ids or using non-sequential ones).
    assert np.array_equal(csr.node_ids, np.arange(m)), (
        "route_on_line_graph assumes line-graph node ids are exactly 0..m-1"
    )

    starts: list[int] = []
    ends: list[int] = []
    for node_id, data in line_graph.nodes(data=True):
        edge_u, edge_v, _ = data["edge_key"]
        if edge_u == origin_real_node:
            starts.append(node_id)
        if edge_v == destination_real_node:
            ends.append(node_id)

    if not starts or not ends:
        return None

    super_source = m
    start_weights = np.array([line_graph.nodes[s]["weight"] for s in starts], dtype=np.float64)
    aug_indptr = np.append(csr.indptr, csr.indptr[-1] + len(starts))
    aug_indices = np.concatenate([csr.indices, np.array(starts, dtype=np.int64)])
    aug_weights = np.concatenate([csr.weights, start_weights])

    result = dijkstra(aug_indptr, aug_indices, aug_weights, source=super_source)

    best_end = min(ends, key=lambda e: result.dist[e])
    if math.isinf(result.dist[best_end]):
        return None

    line_path = reconstruct_path(result.predecessor, super_source, best_end)[1:]
    real_path = [line_graph.nodes[line_path[0]]["edge_key"][0]]
    real_path.extend(line_graph.nodes[n]["edge_key"][1] for n in line_path)

    return real_path, float(result.dist[best_end])
