"""Golden test: nearest-edge snapping vs nearest-node snapping on real data.

Demonstrates the actual bug report this fixes — for an address in the
middle of a long block, `nearest_node` can pick an intersection nowhere
near the road the address is actually on, while `nearest_edge_endpoints`
correctly identifies that road's own two endpoints and, when it's a long
osmnx-merged edge (see `helpers.py`'s module docstring), correctly prices
the cost of actually reaching each one instead of assuming both are free.
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

    snap = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)

    assert {snap.u, snap.v} == {u, v}


def test_approach_cost_reflects_the_real_edges_length_not_zero(prepared_graph):
    # The fixture's longest edge is ~230m of merged street names (a real
    # example of the same osmnx-simplification pattern as the bridge in the
    # original bug report, even though this one isn't a bridge) — querying
    # near its midpoint must show a meaningfully non-zero approach cost to
    # BOTH ends, not the "assume you're already there" behaviour this
    # feature replaces.
    u, v = _longest_edge(prepared_graph)
    mid_x = (prepared_graph.nodes[u]["x"] + prepared_graph.nodes[v]["x"]) / 2
    mid_y = (prepared_graph.nodes[u]["y"] + prepared_graph.nodes[v]["y"]) / 2

    snap = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)

    edge_travel_time = prepared_graph.get_edge_data(snap.u, snap.v, 0)["travel_time"]
    assert snap.approach_to_u > 1.0
    assert snap.approach_to_v > 1.0
    assert snap.approach_to_u + snap.approach_to_v == pytest.approx(edge_travel_time, rel=1e-6)


def test_connector_coords_follow_the_real_road_not_a_straight_line(prepared_graph):
    # The fixture's longest edge has an explicit multi-point 'geometry'
    # (it's a merged, multi-named street) -- the connector must follow it,
    # not jump straight from the query point to the endpoint.
    u, v = _longest_edge(prepared_graph)
    mid_x = (prepared_graph.nodes[u]["x"] + prepared_graph.nodes[v]["x"]) / 2
    mid_y = (prepared_graph.nodes[u]["y"] + prepared_graph.nodes[v]["y"]) / 2

    snap = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)
    assert prepared_graph.get_edge_data(snap.u, snap.v, 0).get("geometry") is not None

    coords = snap.connector_coords(snap.v)
    assert len(coords) > 2  # more than a single straight segment
    # The road curves, so the nearest point ON it can be a little off from
    # the straight-line midpoint between u and v — a generous tolerance
    # here, well inside the ~230m edge's length, still catches a genuinely
    # wrong (e.g. unprojected or mis-transformed) starting point.
    assert coords[0] == pytest.approx((mid_x, mid_y), abs=15.0)
    assert coords[-1] == pytest.approx(
        (prepared_graph.nodes[snap.v]["x"], prepared_graph.nodes[snap.v]["y"]), abs=1e-6
    )


def test_select_best_endpoints_then_picks_one_of_the_correct_roads_two_ends(prepared_graph):
    u, v = _longest_edge(prepared_graph)
    mid_x = (prepared_graph.nodes[u]["x"] + prepared_graph.nodes[v]["x"]) / 2
    mid_y = (prepared_graph.nodes[u]["y"] + prepared_graph.nodes[v]["y"]) / 2

    csr = build_csr(prepared_graph)
    snap = nearest_edge_endpoints(prepared_graph, mid_x, mid_y)
    origin_candidates = tuple(
        (int(np.searchsorted(csr.node_ids, n)), approach) for n, approach in snap.candidates
    )

    # Any real destination far from the origin — the golden fixture's known
    # far corner, used elsewhere in this test suite.
    destination_idx = int(np.searchsorted(csr.node_ids, 12730614170))

    origin, _destination = select_best_endpoints(
        csr.indptr,
        csr.indices,
        csr.weights,
        origin_candidates,
        ((destination_idx, 0.0), (destination_idx, 0.0)),
    )

    assert int(csr.node_ids[origin]) in (u, v)
