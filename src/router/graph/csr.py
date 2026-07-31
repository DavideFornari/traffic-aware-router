"""Adapter from a networkx road graph to CSR arrays.

The routing core (Milestone 3) operates only on this array representation —
it never sees osmnx, networkx, or OSM ids. This module is the one place
where that boundary is crossed, which is what lets the core be swapped
between the OSM node graph and the turn-restriction line graph without
changing a single line of routing code.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np


@dataclass(frozen=True)
class CSRGraph:
    """Compressed-sparse-row representation of a directed weighted graph.

    Node `i`'s out-edges are `indices[indptr[i]:indptr[i + 1]]` (target node
    indices), with matching weights at the same positions in `weights`.
    Each node's out-edges are sorted by target index. `node_ids[i]` is the
    original graph node id (e.g. an OSM node id) for CSR index `i`, and
    `edge_keys[j]` is the `(u, v, key)` of the source graph edge backing
    CSR edge `j`, for mapping a computed route back to geometry.

    `lat`/`lon` (WGS84 degrees, aligned with `node_ids`) are `None` unless
    every source-graph node carries `lat`/`lon` attributes — they exist only
    to feed the A* heuristic (Milestone 3), which needs great-circle
    distance and therefore unprojected coordinates.

    `x`/`y` are `None` unless every node carries `x`/`y` attributes; they are
    whatever CRS was on the graph when `build_csr` ran. The corridor module
    (Milestone 4) requires these to be projected metres — call `build_csr`
    after `prepare_graph`, never on a raw unprojected graph, or the ellipse
    and buffer geometry will be computed in degrees.
    """

    indptr: np.ndarray
    indices: np.ndarray
    weights: np.ndarray
    node_ids: np.ndarray
    edge_keys: list[tuple[int, int, int]]
    lat: np.ndarray | None = None
    lon: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def n_edges(self) -> int:
        return len(self.indices)


def build_csr(graph: nx.MultiDiGraph, weight: str = "travel_time") -> CSRGraph:
    """Convert a directed graph into CSR arrays keyed by `weight`.

    Works on any `MultiDiGraph` with a numeric `weight` edge attribute, not
    just OSM graphs — this is what makes the core testable against small
    hand-built graphs. Parallel edges between the same ordered node pair
    collapse to their minimum-weight edge, since routing only ever wants the
    best one.
    """
    node_ids = np.array(sorted(graph.nodes), dtype=np.int64)
    node_index = {osmid: i for i, osmid in enumerate(node_ids)}
    n = len(node_ids)

    best_edge: dict[tuple[int, int], tuple[float, int]] = {}
    for u, v, k, data in graph.edges(keys=True, data=True):
        w = float(data[weight])
        ui, vi = node_index[u], node_index[v]
        current = best_edge.get((ui, vi))
        if current is None or w < current[0]:
            best_edge[(ui, vi)] = (w, k)

    out_edges: list[list[tuple[int, float, int]]] = [[] for _ in range(n)]
    for (ui, vi), (w, k) in best_edge.items():
        out_edges[ui].append((vi, w, k))
    for edges in out_edges:
        edges.sort(key=lambda e: e[0])

    n_edges = len(best_edge)
    indptr = np.zeros(n + 1, dtype=np.int64)
    indices = np.empty(n_edges, dtype=np.int64)
    weights = np.empty(n_edges, dtype=np.float64)
    edge_keys: list[tuple[int, int, int]] = []

    pos = 0
    for ui in range(n):
        indptr[ui] = pos
        for vi, w, k in out_edges[ui]:
            indices[pos] = vi
            weights[pos] = w
            edge_keys.append((int(node_ids[ui]), int(node_ids[vi]), k))
            pos += 1
    indptr[n] = pos

    def _node_arrays(attr_a: str, attr_b: str) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
        if not all(attr_a in graph.nodes[i] and attr_b in graph.nodes[i] for i in node_ids):
            return None, None
        a = np.array([graph.nodes[osmid][attr_a] for osmid in node_ids], dtype=np.float64)
        b = np.array([graph.nodes[osmid][attr_b] for osmid in node_ids], dtype=np.float64)
        return a, b

    lat, lon = _node_arrays("lat", "lon")
    x, y = _node_arrays("x", "y")

    return CSRGraph(
        indptr=indptr,
        indices=indices,
        weights=weights,
        node_ids=node_ids,
        edge_keys=edge_keys,
        lat=lat,
        lon=lon,
        x=x,
        y=y,
    )
