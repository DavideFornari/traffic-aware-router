"""Unit tests for probe-point placement."""

import numpy as np

from router.traffic.sampling import sample_probe_points


def _line(n_nodes: int, spacing: float = 100.0):
    x = np.arange(n_nodes, dtype=float) * spacing
    y = np.zeros(n_nodes)
    indptr = np.arange(n_nodes + 1, dtype=np.int64)
    indptr[-1] = n_nodes - 1  # last node has no out-edge
    indices = np.arange(1, n_nodes, dtype=np.int64)
    return indptr, indices, x, y


def test_at_least_one_probe_for_a_short_corridor():
    indptr, indices, x, y = _line(2, spacing=50.0)
    probes = sample_probe_points(indptr, indices, x, y, spacing_m=300.0)
    assert len(probes) == 1


def test_probe_count_scales_with_corridor_length():
    indptr, indices, x, y = _line(10, spacing=100.0)  # 900m total
    probes = sample_probe_points(indptr, indices, x, y, spacing_m=300.0)
    # roughly 900/300 = 3 probes
    assert 2 <= len(probes) <= 4


def test_bidirectional_edges_are_sampled_once():
    # 0 <-> 1, both directions present in the CSR arrays.
    indptr = np.array([0, 1, 2])
    indices = np.array([1, 0])
    x = np.array([0.0, 100.0])
    y = np.array([0.0, 0.0])
    probes = sample_probe_points(indptr, indices, x, y, spacing_m=300.0)
    assert len(probes) == 1


def test_probe_midpoint_is_the_edge_midpoint():
    indptr, indices, x, y = _line(2, spacing=100.0)
    probes = sample_probe_points(indptr, indices, x, y, spacing_m=300.0)
    assert probes[0].mid_x == 50.0
    assert probes[0].mid_y == 0.0


def test_no_edges_yields_no_probes():
    indptr = np.array([0, 0, 0])
    indices = np.array([], dtype=np.int64)
    x = np.array([0.0, 1.0])
    y = np.array([0.0, 1.0])
    assert sample_probe_points(indptr, indices, x, y) == []
