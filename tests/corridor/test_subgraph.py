"""Unit tests for induced sub-CSR extraction."""

import numpy as np
import pytest

from router.corridor.subgraph import extract_subgraph


def _square():
    # 0->1(1), 1->2(1), 2->3(1), 3->0(1), 0->2(5) diagonal
    indptr = np.array([0, 2, 3, 4, 5])
    indices = np.array([1, 2, 2, 3, 0])
    weights = np.array([1.0, 5.0, 1.0, 1.0, 1.0])
    return indptr, indices, weights


def test_excluded_node_and_its_edges_disappear():
    indptr, indices, weights = _square()
    mask = np.array([True, True, False, True])  # drop node 2

    sub = extract_subgraph(indptr, indices, weights, mask)

    assert sub.n_nodes == 3
    assert list(sub.sub_to_full) == [0, 1, 3]
    # node 0's only surviving out-edge should be to node 1 (full), not the
    # diagonal to 2 or anything via 2.
    row = sub.indices[sub.indptr[0] : sub.indptr[1]]
    assert list(row) == [sub.full_to_sub[1]]


def test_full_to_sub_is_minus_one_for_excluded_nodes():
    indptr, indices, weights = _square()
    mask = np.array([True, True, False, True])

    sub = extract_subgraph(indptr, indices, weights, mask)

    assert sub.full_to_sub[2] == -1
    assert sub.full_to_sub[0] != -1


def test_full_mask_reproduces_the_original_graph():
    indptr, indices, weights = _square()
    mask = np.array([True, True, True, True])

    sub = extract_subgraph(indptr, indices, weights, mask)

    np.testing.assert_array_equal(sub.indptr, indptr)
    np.testing.assert_array_equal(sub.indices, indices)
    np.testing.assert_array_equal(sub.weights, weights)
    np.testing.assert_array_equal(sub.sub_to_full, np.arange(4))


def test_empty_mask_yields_empty_subgraph():
    indptr, indices, weights = _square()
    mask = np.zeros(4, dtype=bool)

    sub = extract_subgraph(indptr, indices, weights, mask)

    assert sub.n_nodes == 0
    assert sub.n_edges == 0


def test_weights_are_preserved_for_surviving_edges():
    indptr, indices, weights = _square()
    mask = np.array([True, False, True, False])  # keep 0 and 2, drop 1 and 3

    sub = extract_subgraph(indptr, indices, weights, mask)

    # only surviving edge is the diagonal 0->2, weight 5
    assert sub.n_edges == 1
    assert sub.weights[0] == pytest.approx(5.0)
