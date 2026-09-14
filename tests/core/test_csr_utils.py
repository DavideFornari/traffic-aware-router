"""Unit tests for router.core.csr_utils.edge_position."""

import numpy as np

from router.core.csr_utils import edge_position


def _csr(rows: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    indptr = np.zeros(len(rows) + 1, dtype=np.int64)
    indices: list[int] = []
    for i, row in enumerate(rows):
        indices.extend(row)
        indptr[i + 1] = len(indices)
    return indptr, np.array(indices, dtype=np.int64)


def test_finds_edge_at_start_middle_and_end_of_row():
    indptr, indices = _csr([[1, 3, 5]])
    assert edge_position(indptr, indices, 0, 1) == 0
    assert edge_position(indptr, indices, 0, 3) == 1
    assert edge_position(indptr, indices, 0, 5) == 2


def test_returns_none_for_missing_target():
    indptr, indices = _csr([[1, 3, 5]])
    assert edge_position(indptr, indices, 0, 2) is None
    assert edge_position(indptr, indices, 0, 6) is None


def test_returns_none_for_empty_row():
    indptr, indices = _csr([[], [0]])
    assert edge_position(indptr, indices, 0, 0) is None


def test_looks_up_the_correct_row_among_several():
    indptr, indices = _csr([[2], [0, 5], []])
    assert edge_position(indptr, indices, 1, 0) == 1
    assert edge_position(indptr, indices, 1, 5) == 2
