"""Golden tests: fixed origin/destination pairs on the committed Verona fixture.

Compares our Dijkstra and A* against networkx (oracle) and against each
other, on a real (if small) road network rather than synthetic graphs.
"""

from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pytest

from router.core.astar import astar
from router.core.dijkstra import dijkstra, reconstruct_path
from router.graph.csr import build_csr
from router.graph.prepare import max_speed_kph, prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"

# First and last node ids (sorted) in the fixture — a real 9-hop route.
SOURCE_ID = 30691468
TARGET_ID = 12730614170


@pytest.fixture(scope="module")
def prepared_graph():
    raw = ox.load_graphml(FIXTURE)
    return prepare_graph(raw)


def test_dijkstra_matches_networkx_on_the_fixture(prepared_graph):
    csr = build_csr(prepared_graph)
    source = int(np.searchsorted(csr.node_ids, SOURCE_ID))
    target = int(np.searchsorted(csr.node_ids, TARGET_ID))

    result = dijkstra(csr.indptr, csr.indices, csr.weights, source=source, target=target)

    oracle_cost = nx.shortest_path_length(
        prepared_graph, SOURCE_ID, TARGET_ID, weight="travel_time"
    )
    assert result.dist[target] == pytest.approx(oracle_cost, rel=1e-6)


def test_astar_matches_dijkstra_on_the_fixture(prepared_graph):
    csr = build_csr(prepared_graph)
    source = int(np.searchsorted(csr.node_ids, SOURCE_ID))
    target = int(np.searchsorted(csr.node_ids, TARGET_ID))
    v_max_mps = max_speed_kph(prepared_graph) * 1000 / 3600

    dij = dijkstra(csr.indptr, csr.indices, csr.weights, source=source, target=target)
    a_star = astar(
        csr.indptr, csr.indices, csr.weights, csr.lat, csr.lon, v_max_mps, source, target
    )

    assert a_star.dist[target] == pytest.approx(dij.dist[target], rel=1e-6)
    # Admissible heuristic guides search towards the target: never settles more.
    assert a_star.settled_count <= dij.settled_count


def test_reconstructed_path_starts_and_ends_correctly(prepared_graph):
    csr = build_csr(prepared_graph)
    source = int(np.searchsorted(csr.node_ids, SOURCE_ID))
    target = int(np.searchsorted(csr.node_ids, TARGET_ID))

    result = dijkstra(csr.indptr, csr.indices, csr.weights, source=source, target=target)
    path = reconstruct_path(result.predecessor, source, target)

    assert path[0] == source
    assert path[-1] == target
    assert len(path) >= 2
