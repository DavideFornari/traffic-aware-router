"""A* over CSR arrays, using an admissible great-circle-distance heuristic.

`heuristic(u) = great_circle_distance(u, target) / v_max` is admissible: no
travel-time path can beat covering the remaining straight-line distance at
the fastest speed present anywhere in the graph, so the heuristic never
overestimates the true remaining cost. Since edge weights are non-negative
(required by Dijkstra, reused here) and the heuristic is admissible and
consistent (it comes from a metric distance divided by a constant), the
first pop of `target` off the heap carries its true shortest distance,
exactly as in Dijkstra.
"""

from __future__ import annotations

import heapq

import numpy as np

from router.core.dijkstra import INF, ShortestPaths
from router.core.geometry import great_circle_distance_m


def astar(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    v_max: float,
    source: int,
    target: int,
) -> ShortestPaths:
    """Shortest path from `source` to `target` using the heuristic above.

    `lat`/`lon` are per-node WGS84 coordinates aligned with the CSR node
    index; `v_max` is the top edge speed in the graph, in the same distance
    and time units as `weights` (metres and seconds, for OSM travel times).
    """
    if np.any(weights < 0):
        raise ValueError("A* requires non-negative edge weights.")

    n = len(indptr) - 1
    dist = np.full(n, INF)
    predecessor = np.full(n, -1, dtype=np.int64)
    settled = np.zeros(n, dtype=bool)
    settled_count = 0

    def heuristic(u: int) -> float:
        return great_circle_distance_m(lat[u], lon[u], lat[target], lon[target]) / v_max

    dist[source] = 0.0
    heap: list[tuple[float, int]] = [(heuristic(source), source)]

    while heap:
        _, u = heapq.heappop(heap)
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
            nd = dist[u] + weights[pos]
            if nd < dist[v]:
                dist[v] = nd
                predecessor[v] = u
                heapq.heappush(heap, (nd + heuristic(v), v))

    return ShortestPaths(dist=dist, predecessor=predecessor, settled_count=settled_count)
