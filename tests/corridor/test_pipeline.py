"""Golden test: the full corridor pipeline on the committed Verona fixture."""

from pathlib import Path

import numpy as np
import osmnx as ox
import pytest

from router.corridor.pipeline import build_corridor
from router.graph.csr import build_csr
from router.graph.prepare import max_speed_kph, prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"

# Same origin/destination as the routing-core golden tests: a real 9-hop route.
ORIGIN_ID = 30691468
DESTINATION_ID = 12730614170


@pytest.fixture(scope="module")
def csr():
    raw = ox.load_graphml(FIXTURE)
    prepared = prepare_graph(raw)
    return build_csr(prepared), max_speed_kph(prepared) * 1000 / 3600


def test_corridor_contains_origin_and_destination(csr):
    graph, v_max = csr
    origin = int(np.searchsorted(graph.node_ids, ORIGIN_ID))
    destination = int(np.searchsorted(graph.node_ids, DESTINATION_ID))

    result = build_corridor(
        graph.indptr, graph.indices, graph.weights, graph.x, graph.y, origin, destination, v_max
    )

    assert origin in result.subgraph.sub_to_full
    assert destination in result.subgraph.sub_to_full


def test_corridor_is_smaller_than_the_full_graph_but_not_empty(csr):
    graph, v_max = csr
    origin = int(np.searchsorted(graph.node_ids, ORIGIN_ID))
    destination = int(np.searchsorted(graph.node_ids, DESTINATION_ID))

    result = build_corridor(
        graph.indptr, graph.indices, graph.weights, graph.x, graph.y, origin, destination, v_max
    )

    assert 0 < result.subgraph.n_nodes <= graph.n_nodes


def test_candidate_paths_are_cost_ordered_and_start_end_correctly(csr):
    graph, v_max = csr
    origin = int(np.searchsorted(graph.node_ids, ORIGIN_ID))
    destination = int(np.searchsorted(graph.node_ids, DESTINATION_ID))

    result = build_corridor(
        graph.indptr, graph.indices, graph.weights, graph.x, graph.y, origin, destination, v_max
    )

    assert result.candidate_costs == sorted(result.candidate_costs)
    for path in result.candidate_paths:
        assert path[0] == origin
        assert path[-1] == destination


def test_first_candidate_path_cost_equals_t_star(csr):
    graph, v_max = csr
    origin = int(np.searchsorted(graph.node_ids, ORIGIN_ID))
    destination = int(np.searchsorted(graph.node_ids, DESTINATION_ID))

    result = build_corridor(
        graph.indptr, graph.indices, graph.weights, graph.x, graph.y, origin, destination, v_max
    )

    assert result.candidate_costs[0] == pytest.approx(result.t_star, rel=1e-6)


def test_no_path_between_origin_and_destination_raises():
    # two disconnected nodes: 0 has no edges at all.
    indptr = np.array([0, 0, 0])
    indices = np.array([], dtype=np.int64)
    weights = np.array([], dtype=np.float64)
    x = np.array([0.0, 100.0])
    y = np.array([0.0, 0.0])

    with pytest.raises(ValueError, match="No path"):
        build_corridor(indptr, indices, weights, x, y, origin=0, destination=1, v_max=10.0)
