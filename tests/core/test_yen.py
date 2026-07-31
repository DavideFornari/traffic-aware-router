"""Unit tests for Yen's k-shortest-paths on small hand-built CSR arrays."""

import numpy as np
import pytest

from router.core.yen import yen_k_shortest_paths


def _diamond():
    # 0->1(1), 0->2(2), 1->3(1), 2->3(1), 0->3(10)
    indptr = np.array([0, 3, 4, 5, 5])
    indices = np.array([1, 2, 3, 3, 3])
    weights = np.array([1.0, 2.0, 10.0, 1.0, 1.0])
    return indptr, indices, weights


def test_paths_are_returned_in_non_decreasing_cost_order():
    indptr, indices, weights = _diamond()
    result = yen_k_shortest_paths(indptr, indices, weights, 0, 3, k=4)
    costs = [cost for _, cost in result]
    assert costs == sorted(costs)


def test_returns_all_three_loopless_paths_and_no_more():
    indptr, indices, weights = _diamond()
    result = yen_k_shortest_paths(indptr, indices, weights, 0, 3, k=4)
    paths = [path for path, _ in result]
    assert [0, 1, 3] in paths
    assert [0, 2, 3] in paths
    assert [0, 3] in paths
    assert len(result) == 3


def test_k_1_returns_only_the_shortest_path():
    indptr, indices, weights = _diamond()
    result = yen_k_shortest_paths(indptr, indices, weights, 0, 3, k=1)
    assert len(result) == 1
    assert result[0][0] == [0, 1, 3]
    assert result[0][1] == pytest.approx(2.0)


def test_no_path_returns_empty_list():
    indptr = np.array([0, 0, 0])
    indices = np.array([], dtype=np.int64)
    weights = np.array([], dtype=np.float64)
    assert yen_k_shortest_paths(indptr, indices, weights, 0, 1, k=4) == []


def test_paths_are_loopless():
    indptr, indices, weights = _diamond()
    result = yen_k_shortest_paths(indptr, indices, weights, 0, 3, k=4)
    for path, _ in result:
        assert len(path) == len(set(path))
