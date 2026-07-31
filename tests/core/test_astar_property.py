"""Property-based test: A* must return the same cost as Dijkstra.

Edge weights are constructed as `great_circle_distance(u, v) / speed`, with
`speed <= v_max` for every edge. By the triangle inequality on great-circle
distance, this guarantees `heuristic(u) = great_circle_distance(u, target) /
v_max` never overestimates the true remaining cost — i.e. the heuristic is
admissible by construction, which is exactly the condition A*'s correctness
relies on (see astar.py's docstring).
"""

import math

import networkx as nx
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from router.core.astar import astar
from router.core.dijkstra import dijkstra
from router.core.geometry import great_circle_distance_m
from router.graph.csr import build_csr

V_MAX = 30.0  # m/s, upper bound on every edge's implied speed
N_NODES = 8

LAT = st.floats(min_value=45.00, max_value=45.01, allow_nan=False)
LON = st.floats(min_value=10.00, max_value=10.01, allow_nan=False)
SPEED_FRACTION = st.floats(min_value=0.05, max_value=1.0, allow_nan=False)


@st.composite
def admissible_graphs(draw):
    coords = draw(st.lists(st.tuples(LAT, LON), min_size=N_NODES, max_size=N_NODES))
    node_pairs = [(u, v) for u in range(N_NODES) for v in range(N_NODES) if u != v]
    included = draw(st.lists(st.sampled_from(node_pairs), min_size=1, max_size=20, unique=True))
    speeds = draw(st.lists(SPEED_FRACTION, min_size=len(included), max_size=len(included)))
    source, target = draw(st.tuples(st.integers(0, N_NODES - 1), st.integers(0, N_NODES - 1)))
    return coords, included, speeds, source, target


@given(admissible_graphs())
@settings(max_examples=100)
def test_astar_matches_dijkstra_cost(data):
    coords, included, speeds, source, target = data

    g = nx.MultiDiGraph()
    g.add_nodes_from(range(N_NODES))
    for (u, v), fraction in zip(included, speeds, strict=True):
        lat_u, lon_u = coords[u]
        lat_v, lon_v = coords[v]
        distance = great_circle_distance_m(lat_u, lon_u, lat_v, lon_v)
        speed = max(fraction * V_MAX, 1e-6)
        g.add_edge(u, v, weight=distance / speed)

    csr = build_csr(g, weight="weight")
    lat = np.array([coords[node_id][0] for node_id in csr.node_ids])
    lon = np.array([coords[node_id][1] for node_id in csr.node_ids])

    dij = dijkstra(csr.indptr, csr.indices, csr.weights, source=source, target=target)
    a_star = astar(
        csr.indptr, csr.indices, csr.weights, lat, lon, V_MAX, source=source, target=target
    )

    if math.isinf(dij.dist[target]):
        assert math.isinf(a_star.dist[target])
    else:
        assert math.isclose(a_star.dist[target], dij.dist[target], rel_tol=1e-9, abs_tol=1e-9)
