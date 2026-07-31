"""Unit tests for Dijkstra on small hand-built CSR arrays."""

import numpy as np
import pytest

from router.core.dijkstra import dijkstra, reconstruct_path


def test_shortest_path_prefers_cheaper_two_hop_route():
    # 0 -> 1 (1), 1 -> 2 (2), 0 -> 2 (5): the two-hop route (cost 3) wins.
    indptr = np.array([0, 2, 3, 3])
    indices = np.array([1, 2, 2])
    weights = np.array([1.0, 5.0, 2.0])

    result = dijkstra(indptr, indices, weights, source=0)

    assert result.dist[2] == pytest.approx(3.0)
    assert reconstruct_path(result.predecessor, 0, 2) == [0, 1, 2]


def test_unreachable_node_has_infinite_distance():
    # node 2 has no incoming edges.
    indptr = np.array([0, 1, 1, 1])
    indices = np.array([1])
    weights = np.array([1.0])

    result = dijkstra(indptr, indices, weights, source=0)

    assert result.dist[2] == float("inf")
    with pytest.raises(ValueError, match="No path"):
        reconstruct_path(result.predecessor, 0, 2)


def test_source_has_zero_distance_to_itself():
    indptr = np.array([0, 0])
    indices = np.array([], dtype=np.int64)
    weights = np.array([], dtype=np.float64)

    result = dijkstra(indptr, indices, weights, source=0)

    assert result.dist[0] == 0.0
    assert reconstruct_path(result.predecessor, 0, 0) == [0]


def test_target_stops_search_early_but_leaves_correct_distance():
    indptr = np.array([0, 2, 3, 3])
    indices = np.array([1, 2, 2])
    weights = np.array([1.0, 5.0, 2.0])

    result = dijkstra(indptr, indices, weights, source=0, target=2)

    assert result.dist[2] == pytest.approx(3.0)


def test_rejects_negative_weights():
    indptr = np.array([0, 1, 1])
    indices = np.array([1])
    weights = np.array([-1.0])

    with pytest.raises(ValueError, match="non-negative"):
        dijkstra(indptr, indices, weights, source=0)
