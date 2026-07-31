"""Dijkstra's algorithm over CSR arrays, using a binary heap.

Operates on plain numpy arrays only — no osmnx, networkx, or graph-layer
types — so it is directly testable against small hand-built arrays and
property-based random graphs (see CLAUDE.md's layering rule).

Assumes non-negative edge weights. This is what lets a lazy-deletion binary
heap (rather than Bellman-Ford) be correct: once a node is popped with its
final distance, no later relaxation via a longer-but-cheaper edge can beat
it, because every subsequent path extension can only add non-negative cost.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

INF = float("inf")


@dataclass
class ShortestPaths:
    """Result of a single-source shortest-path search.

    `dist[i]` is the shortest distance from the source to node `i` (`inf` if
    unreached). `predecessor[i]` is the node preceding `i` on that shortest
    path (`-1` if `i` is the source or unreached). `settled_count` is how
    many nodes were popped off the heap with their final distance — the
    metric the Milestone 3 benchmark uses to compare Dijkstra against A*.
    """

    dist: np.ndarray
    predecessor: np.ndarray
    settled_count: int


def dijkstra(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    source: int,
    target: int | None = None,
) -> ShortestPaths:
    """Single-source shortest paths from `source`.

    If `target` is given, the search stops as soon as `target` is settled
    (its distance is then final; other entries may be partial/incomplete).
    Edge `weights` must be non-negative — see module docstring.
    """
    if np.any(weights < 0):
        raise ValueError("Dijkstra requires non-negative edge weights.")

    n = len(indptr) - 1
    dist = np.full(n, INF)
    predecessor = np.full(n, -1, dtype=np.int64)
    settled = np.zeros(n, dtype=bool)
    settled_count = 0

    dist[source] = 0.0
    heap: list[tuple[float, int]] = [(0.0, source)]

    while heap:
        d, u = heapq.heappop(heap)
        if settled[u]:
            continue
        settled[u] = True
        settled_count += 1
        if u == target:
            break

        for pos in range(indptr[u], indptr[u + 1]):
            v = int(indices[pos])
            if settled[v]:
                continue
            nd = d + weights[pos]
            if nd < dist[v]:
                dist[v] = nd
                predecessor[v] = u
                heapq.heappush(heap, (nd, v))

    return ShortestPaths(dist=dist, predecessor=predecessor, settled_count=settled_count)


def reconstruct_path(predecessor: np.ndarray, source: int, target: int) -> list[int]:
    """Node index sequence from `source` to `target` given a predecessor array.

    Raises `ValueError` if `target` was never reached.
    """
    if target != source and predecessor[target] == -1:
        raise ValueError(f"No path from node {source} to node {target}.")

    path = [target]
    while path[-1] != source:
        path.append(int(predecessor[path[-1]]))
    path.reverse()
    return path
