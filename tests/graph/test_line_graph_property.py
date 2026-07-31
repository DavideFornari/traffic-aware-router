"""Property-based test: an unrestricted line graph must reproduce the same
route cost as the equivalent path computed directly on the node graph via
networkx — the oracle, as elsewhere in this project.

For a route that starts by using `source_edge = (u, v)` and ends by using
`target_edge = (w, x)`, the true cost is `weight(source_edge) +
shortest_path(v, w) + weight(target_edge)`: the source and target edges
are fixed, but everything in between is free to be optimal. That's exactly
what a line-graph Dijkstra plus `source_edge_weight` should compute, with
no restrictions and zero turn penalty.
"""

import math

import networkx as nx
from hypothesis import given, settings
from hypothesis import strategies as st

from router.core.dijkstra import dijkstra
from router.graph.csr import build_csr
from router.graph.line_graph import build_line_graph, find_line_node, source_edge_weight

NODE_IDS = st.integers(min_value=0, max_value=7)
WEIGHTS = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)


def _add_coords(g: nx.MultiDiGraph) -> None:
    for n in g.nodes:
        g.nodes[n]["x"] = float(n)
        g.nodes[n]["y"] = 0.0
        g.nodes[n]["lat"] = 0.0
        g.nodes[n]["lon"] = float(n)


@st.composite
def random_digraphs_with_two_edges(draw):
    edges = draw(
        st.lists(
            st.tuples(NODE_IDS, NODE_IDS, WEIGHTS).filter(lambda e: e[0] != e[1]),
            min_size=2,
            max_size=20,
            unique_by=lambda e: (e[0], e[1]),
        )
    )
    source_edge = draw(st.sampled_from(edges))
    target_edge = draw(st.sampled_from(edges))
    return edges, source_edge, target_edge


@given(random_digraphs_with_two_edges())
@settings(max_examples=150)
def test_unrestricted_line_graph_cost_matches_node_graph_oracle(data):
    edges, source_edge, target_edge = data
    u, v, _ = source_edge
    w, x, _ = target_edge

    g = nx.MultiDiGraph()
    g.add_nodes_from(range(8))
    _add_coords(g)
    for a, b, wt in edges:
        g.add_edge(a, b, travel_time=wt, osmid=0)

    line_graph = build_line_graph(g, weight="travel_time")
    csr = build_csr(line_graph, weight="weight")

    src_node = find_line_node(line_graph, (u, v, 0))
    dst_node = find_line_node(line_graph, (w, x, 0))

    result = dijkstra(csr.indptr, csr.indices, csr.weights, src_node, dst_node)

    if src_node == dst_node:
        # Source and target are literally the same edge: the route is just
        # that edge once, no "middle" — the general oracle below assumes
        # source and target are distinct hops and would double-count it.
        total_cost = result.dist[dst_node] + source_edge_weight(line_graph, src_node)
        assert total_cost == g.edges[u, v, 0]["travel_time"]
        return

    try:
        middle_cost = nx.shortest_path_length(g, v, w, weight="travel_time")
        reachable = True
    except nx.NetworkXNoPath:
        reachable = False

    if not reachable:
        assert math.isinf(result.dist[dst_node])
        return

    assert not math.isinf(result.dist[dst_node])
    total_cost = result.dist[dst_node] + source_edge_weight(line_graph, src_node)
    expected = g.edges[u, v, 0]["travel_time"] + middle_cost + g.edges[w, x, 0]["travel_time"]

    assert math.isclose(total_cost, expected, rel_tol=1e-9, abs_tol=1e-9)
