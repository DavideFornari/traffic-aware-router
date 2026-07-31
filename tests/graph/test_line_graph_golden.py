"""Golden test: the line-graph adapter on the committed Verona fixture."""

from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pytest

from router.core.dijkstra import dijkstra
from router.graph.csr import build_csr
from router.graph.line_graph import (
    build_line_graph,
    find_line_node,
    route_on_line_graph,
    source_edge_weight,
)
from router.graph.prepare import prepare_graph
from router.graph.restrictions import TurnRestriction

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"

SOURCE_NODE = 30691468
TARGET_NODE = 12730614170


@pytest.fixture(scope="module")
def prepared_graph():
    raw = ox.load_graphml(FIXTURE)
    return prepare_graph(raw)


def test_line_graph_node_count_is_the_full_graphs_edge_count(prepared_graph):
    line_graph = build_line_graph(prepared_graph)
    assert line_graph.number_of_nodes() == prepared_graph.number_of_edges()


def test_unrestricted_line_graph_matches_node_graph_between_real_edges(prepared_graph):
    # The first and last edges of the known 9-hop shortest path between
    # SOURCE_NODE and TARGET_NODE (see the routing-core golden tests) —
    # guaranteed reachable, unlike an arbitrary out/in edge pair on a
    # directed graph with one-way streets.
    known_path = nx.shortest_path(prepared_graph, SOURCE_NODE, TARGET_NODE, weight="travel_time")

    def _min_weight_key(a: int, b: int) -> int:
        return min(prepared_graph[a][b], key=lambda k: prepared_graph[a][b][k]["travel_time"])

    source_edge = (known_path[0], known_path[1], _min_weight_key(known_path[0], known_path[1]))
    target_edge = (
        known_path[-2],
        known_path[-1],
        _min_weight_key(known_path[-2], known_path[-1]),
    )
    u, v, _ = source_edge
    w, x, _ = target_edge

    line_graph = build_line_graph(prepared_graph)
    csr = build_csr(line_graph, weight="weight")

    src_node = find_line_node(line_graph, source_edge)
    dst_node = find_line_node(line_graph, target_edge)

    result = dijkstra(csr.indptr, csr.indices, csr.weights, src_node, dst_node)
    total_cost = result.dist[dst_node] + source_edge_weight(line_graph, src_node)

    middle_cost = nx.shortest_path_length(prepared_graph, v, w, weight="travel_time")
    expected = (
        prepared_graph.edges[source_edge]["travel_time"]
        + middle_cost
        + prepared_graph.edges[target_edge]["travel_time"]
    )

    assert total_cost == pytest.approx(expected, rel=1e-6)


def test_banning_the_only_turn_out_of_the_source_edge_makes_it_unreachable(prepared_graph):
    source_edge = next(iter(prepared_graph.out_edges(SOURCE_NODE, keys=True)))
    via_node = source_edge[1]

    # Ban every real turn out of `source_edge` at its immediate via node.
    bans = [
        TurnRestriction(
            from_edge=source_edge, via_node=via_node, to_edge=to_edge, restriction_type="no_entry"
        )
        for to_edge in prepared_graph.out_edges(via_node, keys=True)
    ]

    line_graph = build_line_graph(prepared_graph, restrictions=bans)
    src_node = find_line_node(line_graph, source_edge)

    assert line_graph.out_degree(src_node) == 0


def test_route_on_line_graph_matches_node_graph_dijkstra_when_unrestricted(prepared_graph):
    node_csr = build_csr(prepared_graph)
    source = int(np.searchsorted(node_csr.node_ids, SOURCE_NODE))
    target = int(np.searchsorted(node_csr.node_ids, TARGET_NODE))
    node_result = dijkstra(
        node_csr.indptr, node_csr.indices, node_csr.weights, source=source, target=target
    )

    line_graph = build_line_graph(prepared_graph)
    line_route = route_on_line_graph(line_graph, SOURCE_NODE, TARGET_NODE)

    assert line_route is not None
    _, line_cost = line_route
    assert line_cost == pytest.approx(float(node_result.dist[target]), rel=1e-6)


def test_route_on_line_graph_reroutes_around_a_ban_on_the_optimal_path(prepared_graph):
    # Ban the first turn of the known-optimal route; the line-graph route
    # must still reach the destination (the network has alternatives) at a
    # cost no cheaper than the unrestricted route (banning something can
    # only make the trip as good or worse, never better).
    known_path = nx.shortest_path(prepared_graph, SOURCE_NODE, TARGET_NODE, weight="travel_time")
    from_edge = (known_path[0], known_path[1], 0)
    via_node = known_path[1]
    to_edge = (known_path[1], known_path[2], 0)
    ban = TurnRestriction(
        from_edge=from_edge, via_node=via_node, to_edge=to_edge, restriction_type="no_left_turn"
    )

    unrestricted = route_on_line_graph(build_line_graph(prepared_graph), SOURCE_NODE, TARGET_NODE)
    restricted = route_on_line_graph(
        build_line_graph(prepared_graph, restrictions=[ban]), SOURCE_NODE, TARGET_NODE
    )

    assert unrestricted is not None
    assert restricted is not None
    _, unrestricted_cost = unrestricted
    _, restricted_cost = restricted
    assert restricted_cost >= unrestricted_cost - 1e-6
