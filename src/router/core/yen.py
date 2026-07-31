"""Yen's algorithm for the k shortest loopless paths, built on `dijkstra`.

Standard formulation (Yen, 1971): find the shortest path, then repeatedly
generate "spur" candidates by, for each prefix of the last accepted path,
detouring from a node on that prefix while forbidding the edges and nodes
already used by accepted paths sharing the same prefix — which is exactly
what stops the algorithm from just re-finding the same path or looping back
through it. The k best candidates found this way, in cost order, are the k
shortest paths.

No changes to `dijkstra` are needed: "removing" an edge or node for one spur
computation is done by copying the weight array and setting the relevant
entries to infinity, which `dijkstra` already treats as "no edge".
"""

from __future__ import annotations

import heapq
from itertools import pairwise

import numpy as np

from router.core.dijkstra import INF, dijkstra, reconstruct_path


def _edge_position(indptr: np.ndarray, indices: np.ndarray, u: int, v: int) -> int | None:
    for pos in range(indptr[u], indptr[u + 1]):
        if indices[pos] == v:
            return pos
    return None


def _path_cost(
    indptr: np.ndarray, indices: np.ndarray, weights: np.ndarray, path: list[int]
) -> float:
    total = 0.0
    for u, v in pairwise(path):
        pos = _edge_position(indptr, indices, u, v)
        total += weights[pos]
    return total


def yen_k_shortest_paths(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    source: int,
    target: int,
    k: int = 4,
) -> list[tuple[list[int], float]]:
    """The `k` shortest loopless paths from `source` to `target`, cheapest first.

    Returns fewer than `k` paths if the graph doesn't have that many
    loopless source-target paths. Each result is `(path, cost)` with `path`
    a list of node indices including both endpoints.
    """
    first = dijkstra(indptr, indices, weights, source=source, target=target)
    if np.isinf(first.dist[target]):
        return []

    accepted: list[list[int]] = [reconstruct_path(first.predecessor, source, target)]
    accepted_costs: list[float] = [float(first.dist[target])]

    candidates: list[tuple[float, list[int]]] = []
    seen: set[tuple[int, ...]] = {tuple(accepted[0])}

    while len(accepted) < k:
        prev_path = accepted[-1]

        for i in range(len(prev_path) - 1):
            spur_node = prev_path[i]
            root_path = prev_path[: i + 1]

            blocked_weights = weights.copy()
            for path in accepted:
                if path[: i + 1] == root_path:
                    pos = _edge_position(indptr, indices, path[i], path[i + 1])
                    if pos is not None:
                        blocked_weights[pos] = INF

            for node in root_path[:-1]:
                blocked_weights[indptr[node] : indptr[node + 1]] = INF

            spur_result = dijkstra(
                indptr, indices, blocked_weights, source=spur_node, target=target
            )
            if np.isinf(spur_result.dist[target]):
                continue

            spur_path = reconstruct_path(spur_result.predecessor, spur_node, target)
            total_path = root_path[:-1] + spur_path
            key = tuple(total_path)
            if key in seen:
                continue
            seen.add(key)

            root_cost = _path_cost(indptr, indices, weights, root_path)
            total_cost = root_cost + float(spur_result.dist[target])
            heapq.heappush(candidates, (total_cost, total_path))

        if not candidates:
            break

        cost, path = heapq.heappop(candidates)
        accepted.append(path)
        accepted_costs.append(cost)

    return list(zip(accepted, accepted_costs, strict=True))
