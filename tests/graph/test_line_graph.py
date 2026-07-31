"""Unit tests for the line-graph adapter on small hand-built graphs."""

import networkx as nx
import pytest

from router.core.dijkstra import dijkstra
from router.graph.csr import build_csr
from router.graph.line_graph import (
    build_line_graph,
    find_line_node,
    source_edge_weight,
)
from router.graph.restrictions import TurnRestriction


def _y_junction() -> nx.MultiDiGraph:
    # 1 -> 100 -> 2  and  1 -> 100 -> 3: a junction with two ways out.
    g = nx.MultiDiGraph()
    g.add_node(1, x=0, y=0, lat=0.0, lon=0.0)
    g.add_node(100, x=10, y=0, lat=0.0, lon=0.0001)
    g.add_node(2, x=20, y=0, lat=0.0, lon=0.0002)
    g.add_node(3, x=10, y=10, lat=0.0001, lon=0.0001)
    g.add_edge(1, 100, key=0, osmid=10, travel_time=5.0)
    g.add_edge(100, 2, key=0, osmid=20, travel_time=3.0)
    g.add_edge(100, 3, key=0, osmid=30, travel_time=4.0)
    return g


def test_line_graph_has_one_node_per_directed_edge():
    lg = build_line_graph(_y_junction())
    assert lg.number_of_nodes() == 3


def test_line_graph_node_carries_head_node_coordinates():
    lg = build_line_graph(_y_junction())
    node_id = find_line_node(lg, (1, 100, 0))
    # head of edge (1, 100) is node 100, at x=10, y=0
    assert lg.nodes[node_id]["x"] == 10
    assert lg.nodes[node_id]["y"] == 0


def test_arc_weight_is_the_destination_edges_travel_time():
    lg = build_line_graph(_y_junction())
    src = find_line_node(lg, (1, 100, 0))
    dst = find_line_node(lg, (100, 2, 0))
    assert lg.get_edge_data(src, dst)[0]["weight"] == pytest.approx(3.0)


def test_total_route_cost_includes_source_edges_own_weight():
    g = _y_junction()
    lg = build_line_graph(g)
    csr = build_csr(lg, weight="weight")
    src = find_line_node(lg, (1, 100, 0))
    dst = find_line_node(lg, (100, 2, 0))

    result = dijkstra(csr.indptr, csr.indices, csr.weights, src, dst)
    total_cost = result.dist[dst] + source_edge_weight(lg, src)

    assert total_cost == pytest.approx(5.0 + 3.0)


def test_no_turn_restriction_removes_the_arc():
    g = _y_junction()
    restriction = TurnRestriction(
        from_edge=(1, 100, 0), via_node=100, to_edge=(100, 2, 0), restriction_type="no_left_turn"
    )
    lg = build_line_graph(g, restrictions=[restriction])

    src = find_line_node(lg, (1, 100, 0))
    dst = find_line_node(lg, (100, 2, 0))
    assert not lg.has_edge(src, dst)
    # the other turn (to node 3) is untouched.
    other_dst = find_line_node(lg, (100, 3, 0))
    assert lg.has_edge(src, other_dst)


def test_only_restriction_removes_every_other_arc_for_that_from_edge():
    g = _y_junction()
    restriction = TurnRestriction(
        from_edge=(1, 100, 0),
        via_node=100,
        to_edge=(100, 3, 0),
        restriction_type="only_straight_on",
    )
    lg = build_line_graph(g, restrictions=[restriction])

    src = find_line_node(lg, (1, 100, 0))
    assert lg.out_degree(src) == 1
    allowed = find_line_node(lg, (100, 3, 0))
    assert lg.has_edge(src, allowed)


def test_u_turn_penalty_only_applies_to_reversal_arcs():
    g = nx.MultiDiGraph()
    g.add_node(1, x=0, y=0, lat=0.0, lon=0.0)
    g.add_node(100, x=10, y=0, lat=0.0, lon=0.0001)
    g.add_node(2, x=20, y=0, lat=0.0, lon=0.0002)
    g.add_edge(1, 100, key=0, osmid=10, travel_time=5.0)
    g.add_edge(100, 1, key=0, osmid=10, travel_time=5.0)  # reverse of the above: a U-turn
    g.add_edge(100, 2, key=0, osmid=20, travel_time=3.0)  # continuing straight: not a U-turn

    lg = build_line_graph(g, u_turn_penalty_s=100.0)
    src = find_line_node(lg, (1, 100, 0))

    u_turn_dst = find_line_node(lg, (100, 1, 0))
    straight_dst = find_line_node(lg, (100, 2, 0))

    assert lg.get_edge_data(src, u_turn_dst)[0]["weight"] == pytest.approx(5.0 + 100.0)
    assert lg.get_edge_data(src, straight_dst)[0]["weight"] == pytest.approx(3.0)


def test_unrecognised_restriction_type_is_ignored():
    g = _y_junction()
    restriction = TurnRestriction(
        from_edge=(1, 100, 0), via_node=100, to_edge=(100, 2, 0), restriction_type="weird_tag"
    )
    lg = build_line_graph(g, restrictions=[restriction])
    src = find_line_node(lg, (1, 100, 0))
    dst = find_line_node(lg, (100, 2, 0))
    assert lg.has_edge(src, dst)
