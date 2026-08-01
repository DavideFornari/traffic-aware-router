"""Unit tests for app/helpers.py — the UI's pure, Streamlit-free logic."""

import networkx as nx
import numpy as np
import pytest
from app.helpers import (
    format_delta,
    format_duration,
    nearest_edge_endpoints,
    nearest_node,
    parse_latlon,
    path_to_latlon,
    select_best_endpoints,
    source_node_of_position,
    traffic_summary,
)

from router.traffic.pipeline import TrafficResult


def test_nearest_node_picks_the_closest_point():
    lat = np.array([45.0, 45.1, 46.0])
    lon = np.array([10.0, 10.0, 10.0])
    assert nearest_node(lat, lon, (45.09, 10.0)) == 1


def test_path_to_latlon_pairs_coordinates_in_path_order():
    lat = np.array([1.0, 2.0, 3.0])
    lon = np.array([10.0, 20.0, 30.0])
    assert path_to_latlon([2, 0], lat, lon) == [(3.0, 30.0), (1.0, 10.0)]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 s"), (45, "45 s"), (59.9, "60 s"), (60, "1 min 00 s"), (750, "12 min 30 s")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_delta_signs_positive_and_negative():
    assert format_delta(130) == "+2 min 10 s"
    assert format_delta(-45) == "-45 s"
    assert format_delta(0) == "+0 s"


def test_source_node_of_position_maps_back_to_the_owning_row():
    indptr = np.array([0, 2, 3, 3])
    assert [source_node_of_position(indptr, p) for p in range(3)] == [0, 0, 1]


def test_traffic_summary_no_key():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=0, probes_matched=0)
    assert "No TomTom API key" in traffic_summary(result)


def test_traffic_summary_no_matches():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=5, probes_matched=0)
    assert "none matched" in traffic_summary(result)


def test_traffic_summary_with_matches():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=5, probes_matched=3)
    assert traffic_summary(result) == "Live traffic matched 3 of 5 probes."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45.43, 10.99", (45.43, 10.99)),
        ("45.43,10.99", (45.43, 10.99)),
        ("not a coordinate", None),
        ("200, 10", None),
        ("45.43", None),
    ],
)
def test_parse_latlon(text, expected):
    assert parse_latlon(text) == expected


def _two_edge_graph() -> nx.MultiDiGraph:
    # 1 --- 2 --- 3, a bent road: (0,0) -> (100,0) -> (100,100).
    g = nx.MultiDiGraph()
    g.graph["crs"] = "EPSG:32632"
    g.add_node(1, x=0.0, y=0.0)
    g.add_node(2, x=100.0, y=0.0)
    g.add_node(3, x=100.0, y=100.0)
    g.add_edge(1, 2, key=0, osmid=10, travel_time=10.0)
    g.add_edge(2, 3, key=0, osmid=20, travel_time=10.0)
    return g


def test_nearest_edge_endpoints_picks_the_edge_the_point_actually_sits_on():
    g = _two_edge_graph()
    # near the middle of the first leg, off to the side — mid-block, not at
    # either intersection, which is exactly the address/click case this
    # function exists for (see helpers.py's module comparison to
    # nearest_node).
    assert nearest_edge_endpoints(g, 40.0, 2.0) == (1, 2)
    assert nearest_edge_endpoints(g, 95.0, 50.0) == (2, 3)


def test_nearest_edge_endpoints_finds_the_same_edge_near_either_end():
    g = _two_edge_graph()
    assert nearest_edge_endpoints(g, 5.0, 1.0) == (1, 2)
    assert nearest_edge_endpoints(g, 95.0, 1.0) == (1, 2)


def test_select_best_endpoints_prefers_the_cheaper_route_not_the_nearer_node():
    # Candidate node 1 is geometrically "the wrong side" but has a cheap
    # route to the destination; candidate node 0 has none at all (no
    # out-edges) — select_best_endpoints must pick 1, since it answers a
    # routing question, not a proximity one.
    indptr = np.array([0, 0, 1, 1])
    indices = np.array([2])
    weights = np.array([1.0])

    origin, destination = select_best_endpoints(
        indptr, indices, weights, origin_candidates=(0, 1), destination_candidates=(2,)
    )
    assert origin == 1
    assert destination == 2


def test_select_best_endpoints_checks_all_four_combinations():
    # 0 -> 2 costs 100; 1 -> 3 costs 1 — the cheapest combination spans both
    # a non-default origin candidate AND a non-default destination
    # candidate, so a shortcut that only tries the first of each would miss
    # it.
    indptr = np.array([0, 1, 2, 2, 2])
    indices = np.array([2, 3])
    weights = np.array([100.0, 1.0])

    origin, destination = select_best_endpoints(
        indptr, indices, weights, origin_candidates=(0, 1), destination_candidates=(2, 3)
    )
    assert (origin, destination) == (1, 3)


def test_select_best_endpoints_handles_duplicate_candidates():
    # Both "candidates" are the same node (e.g. a dead-end edge) — must not
    # crash on a degenerate 1-vs-1 comparison.
    indptr = np.array([0, 1, 1])
    indices = np.array([1])
    weights = np.array([5.0])

    origin, destination = select_best_endpoints(
        indptr, indices, weights, origin_candidates=(0, 0), destination_candidates=(1, 1)
    )
    assert (origin, destination) == (0, 1)
