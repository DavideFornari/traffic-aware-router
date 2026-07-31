"""Property-based test: our Dijkstra must match networkx's, our test oracle.

networkx is only ever used here as ground truth (see CLAUDE.md) — the core
implementation never calls into it.
"""

import math

import networkx as nx
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from router.core.dijkstra import dijkstra
from router.graph.csr import build_csr

NODE_IDS = st.integers(min_value=0, max_value=9)
WEIGHTS = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)


@st.composite
def random_digraphs(draw):
    edges = draw(
        st.lists(
            st.tuples(NODE_IDS, NODE_IDS, WEIGHTS).filter(lambda e: e[0] != e[1]),
            min_size=0,
            max_size=25,
        )
    )
    source = draw(NODE_IDS)
    return edges, source


@given(random_digraphs())
@settings(max_examples=200)
def test_dijkstra_matches_networkx_oracle(data):
    edges, source = data

    g = nx.MultiDiGraph()
    g.add_nodes_from(range(10))
    for u, v, w in edges:
        g.add_edge(u, v, weight=w)

    csr = build_csr(g, weight="weight")
    result = dijkstra(csr.indptr, csr.indices, csr.weights, source=source)

    oracle = nx.single_source_dijkstra_path_length(g, source, weight="weight")

    for i, node_id in enumerate(csr.node_ids):
        if node_id in oracle:
            assert math.isclose(result.dist[i], oracle[node_id], rel_tol=1e-9, abs_tol=1e-9)
        else:
            assert result.dist[i] == float("inf")


@given(random_digraphs())
@settings(max_examples=100)
def test_dijkstra_distances_are_non_negative_and_finite_or_inf(data):
    edges, source = data

    g = nx.MultiDiGraph()
    g.add_nodes_from(range(10))
    for u, v, w in edges:
        g.add_edge(u, v, weight=w)

    csr = build_csr(g, weight="weight")
    result = dijkstra(csr.indptr, csr.indices, csr.weights, source=source)

    assert np.all((result.dist >= 0) | np.isinf(result.dist))
