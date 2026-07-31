"""CSR adapter tests on small hand-built graphs — no network, no OSM.

The adapter is graph-agnostic by design (see CLAUDE.md's layering rule), so
it must work on any weighted MultiDiGraph, not just ones built from OSM data.
"""

import networkx as nx
import numpy as np
import pytest

from router.graph.csr import build_csr


def _triangle() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_edge(10, 20, travel_time=1.0)
    g.add_edge(20, 30, travel_time=2.0)
    g.add_edge(10, 30, travel_time=5.0)
    return g


def test_node_ids_sorted_and_indexed():
    csr = build_csr(_triangle())
    assert csr.n_nodes == 3
    assert list(csr.node_ids) == [10, 20, 30]


def test_out_edges_of_each_node_sorted_by_target_index():
    csr = build_csr(_triangle())
    # node 10 -> index 0, has edges to 20 (idx 1) and 30 (idx 2)
    row = csr.indices[csr.indptr[0] : csr.indptr[1]]
    assert list(row) == [1, 2]


def test_weights_match_source_graph():
    csr = build_csr(_triangle())
    row_start, row_end = csr.indptr[0], csr.indptr[1]
    weights = dict(zip(csr.indices[row_start:row_end], csr.weights[row_start:row_end], strict=True))
    assert weights[1] == pytest.approx(1.0)  # 10 -> 20
    assert weights[2] == pytest.approx(5.0)  # 10 -> 30


def test_parallel_edges_collapse_to_minimum_weight():
    g = nx.MultiDiGraph()
    g.add_edge(1, 2, travel_time=9.0)
    g.add_edge(1, 2, travel_time=3.0)
    g.add_edge(1, 2, travel_time=7.0)
    csr = build_csr(g)
    assert csr.n_edges == 1
    assert csr.weights[0] == pytest.approx(3.0)


def test_edge_keys_map_back_to_source_graph_edge():
    g = nx.MultiDiGraph()
    g.add_edge(100, 200, key=0, travel_time=9.0)
    g.add_edge(100, 200, key=1, travel_time=3.0)
    csr = build_csr(g)
    assert csr.edge_keys == [(100, 200, 1)]


def test_isolated_node_has_empty_out_edge_range():
    g = _triangle()
    g.add_node(999)
    csr = build_csr(g)
    idx = int(np.searchsorted(csr.node_ids, 999))
    assert csr.indptr[idx] == csr.indptr[idx + 1]


def test_indptr_is_monotonic_and_spans_all_edges():
    csr = build_csr(_triangle())
    assert np.all(np.diff(csr.indptr) >= 0)
    assert csr.indptr[-1] == csr.n_edges


def test_custom_weight_attribute():
    g = nx.MultiDiGraph()
    g.add_edge(1, 2, travel_time=1.0, length=100.0)
    csr = build_csr(g, weight="length")
    assert csr.weights[0] == pytest.approx(100.0)
