"""Golden test: nearest-edge snapping vs nearest-node snapping on real data.

Demonstrates the actual bug report this fixes — for an address in the
middle of a long block, `nearest_node` can pick an intersection nowhere
near the road the address is actually on, while `nearest_edge_endpoints`
correctly identifies that road's own two endpoints.
"""

from pathlib import Path

import numpy as np
import osmnx as ox
import pytest
from app.helpers import nearest_edge_endpoints, nearest_node, select_best_endpoints

from router.graph.csr import build_csr
from router.graph.prepare import prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"


@pytest.fixture(scope="module")
def prepared_graph():
    raw = ox.load_graphml(FIXTURE)
    return prepare_graph(raw)


def _longest_edge(graph):
    best = None
    for u, v, _key, _data in graph.edges(keys=True, data=True):
        dx = graph.nodes[v]["x"] - graph.nodes[u]["x"]
        dy = graph.nodes[v]["y"] - graph.nodes[u]["y"]
        length = (dx**2 + dy**2) ** 0.5
        if best is None or length > best[0]:
            best = (length, u, v)
    return best[1], best[2]


def test_nearest_node_can_pick_an_unrelated_intersection_mid_block(prepared_graph):
    """Establishes the bug exists in `nearest_node`, for contrast with the fix below."""
    u, v = _longest_edge(prepared_graph)
    mid_lat = (prepared_graph.nodes[u]["lat"] + prepared_graph.nodes[v]["lat"]) / 2
    mid_lon = (prepared_graph.nodes[u]["lon"] + prepared_graph.nodes[v]["lon"]) / 2

    csr = build_csr(prepared_graph)
    node_idx = nearest_node(csr.lat, csr.lon, (mid_lat, mid_lon))
    node_id = int(csr.node_ids[node_idx])

    assert node_id not in (u, v)


def test_nearest_edge_endpoints_finds_the_actual_road_at_the_same_point(prepared_graph):
    u, v = _longest_edge(prepared_graph)
    mid_x = (prepared_graph.nodes[u]["x"] + prepared_graph.nodes[v]["x"]) / 2
    mid_y = (prepared_graph.nodes[u]["y"] + prepared_graph.nodes[v]["y"]) / 2

    edge_u, edge_v = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)

    assert {edge_u, edge_v} == {u, v}


def test_select_best_endpoints_then_picks_one_of_the_correct_roads_two_ends(prepared_graph):
    u, v = _longest_edge(prepared_graph)
    mid_x = (prepared_graph.nodes[u]["x"] + prepared_graph.nodes[v]["x"]) / 2
    mid_y = (prepared_graph.nodes[u]["y"] + prepared_graph.nodes[v]["y"]) / 2

    csr = build_csr(prepared_graph)
    edge_u, edge_v = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)
    origin_candidates = tuple(int(np.searchsorted(csr.node_ids, n)) for n in (edge_u, edge_v))

    # Any real destination far from the origin — the golden fixture's known
    # far corner, used elsewhere in this test suite.
    destination_idx = int(np.searchsorted(csr.node_ids, 12730614170))

    origin, _destination = select_best_endpoints(
        csr.indptr,
        csr.indices,
        csr.weights,
        origin_candidates,
        (destination_idx, destination_idx),
    )

    assert int(csr.node_ids[origin]) in (u, v)
