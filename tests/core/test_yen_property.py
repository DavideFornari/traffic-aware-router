"""Property-based test: Yen's k-shortest-paths costs must match networkx's.

networkx's `shortest_simple_paths` yields loopless simple paths in
non-decreasing cost order — the same contract `yen_k_shortest_paths`
promises — so it's the oracle here, as elsewhere in this project.

Costs, not paths, are compared: when several paths tie on cost, the two
implementations may break the tie differently, but the *set* of achievable
costs for the k cheapest loopless paths must be identical.
"""

import itertools
from math import isclose

import networkx as nx
from hypothesis import given, settings
from hypothesis import strategies as st

from router.core.yen import yen_k_shortest_paths
from router.graph.csr import build_csr

NODE_IDS = st.integers(min_value=0, max_value=7)
WEIGHTS = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)
K = 3


@st.composite
def random_digraphs(draw):
    edges = draw(
        st.lists(
            st.tuples(NODE_IDS, NODE_IDS, WEIGHTS).filter(lambda e: e[0] != e[1]),
            min_size=0,
            max_size=20,
        )
    )
    source, target = draw(st.tuples(NODE_IDS, NODE_IDS).filter(lambda st_: st_[0] != st_[1]))
    return edges, source, target


@given(random_digraphs())
@settings(max_examples=150)
def test_yen_costs_match_networkx_oracle(data):
    edges, source, target = data

    g = nx.MultiDiGraph()
    g.add_nodes_from(range(8))
    for u, v, w in edges:
        g.add_edge(u, v, weight=w)

    csr = build_csr(g, weight="weight")
    source_idx = int(source)
    target_idx = int(target)

    ours = yen_k_shortest_paths(csr.indptr, csr.indices, csr.weights, source_idx, target_idx, k=K)
    our_costs = sorted(cost for _, cost in ours)

    # shortest_simple_paths doesn't support multigraphs: collapse parallel
    # edges to their minimum weight first, exactly as build_csr does.
    simple = nx.DiGraph()
    simple.add_nodes_from(range(8))
    for u, v, w in edges:
        if not simple.has_edge(u, v) or w < simple[u][v]["weight"]:
            simple.add_edge(u, v, weight=w)

    try:
        oracle_paths = list(
            itertools.islice(
                nx.shortest_simple_paths(simple, source_idx, target_idx, weight="weight"), K
            )
        )
    except nx.NetworkXNoPath:
        oracle_paths = []

    oracle_costs = sorted(nx.path_weight(simple, path, weight="weight") for path in oracle_paths)

    assert len(our_costs) == len(oracle_costs)
    for ours_cost, oracle_cost in zip(our_costs, oracle_costs, strict=True):
        assert isclose(ours_cost, oracle_cost, rel_tol=1e-9, abs_tol=1e-9)
