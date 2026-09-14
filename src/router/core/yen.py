"""Yen's algorithm for the k shortest loopless paths, built on `dijkstra`.

Standard formulation (Yen, 1971): find the shortest path, then repeatedly
generate "spur" candidates by, for each prefix of the last accepted path,
detouring from a node on that prefix while forbidding the edges and nodes
already used by accepted paths sharing the same prefix — which is exactly
what stops the algorithm from just re-finding the same path or looping back
through it. The k best candidates found this way, in cost order, are the k
shortest paths.

"Removing" an edge or node for one spur computation is done by temporarily
setting the relevant `weights` entries to `INF` (which `dijkstra` already
treats as "no edge") and restoring them once that spur's search returns,
rather than copying the whole weight array per spur — for a corridor-sized
graph the blocked set per spur is normally a handful of edges plus a few
node out-degrees, orders of magnitude smaller than the full edge count.
`weights` is validated non-negative once up front, then passed to
`dijkstra(..., validate=False)` for every spur search: every value we ever
write is `INF` or a restored original (already known non-negative), so the
per-spur O(E) re-check `dijkstra` would otherwise do is redundant here.
"""

from __future__ import annotations

import heapq
from itertools import pairwise

import numpy as np

from router.core.csr_utils import edge_position
from router.core.dijkstra import INF, dijkstra, reconstruct_path


def _path_cost(
    indptr: np.ndarray, indices: np.ndarray, weights: np.ndarray, path: list[int]
) -> float:
    total = 0.0
    for u, v in pairwise(path):
        pos = edge_position(indptr, indices, u, v)
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

    `weights` is mutated in place while a spur is being searched and always
    restored (even on exception) before this function returns or moves on
    to the next spur — see module docstring. Not safe to call concurrently
    from multiple threads against the same `weights` array; the corridor
    pipeline that's the only current caller only ever calls this
    single-threaded.
    """
    if np.any(weights < 0):
        raise ValueError("Yen requires non-negative edge weights.")

    first = dijkstra(indptr, indices, weights, source=source, target=target, validate=False)
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

            touched_edges: set[int] = set()
            edge_saves: list[tuple[int, float]] = []
            for path in accepted:
                if path[: i + 1] == root_path:
                    pos = edge_position(indptr, indices, path[i], path[i + 1])
                    if pos is not None and pos not in touched_edges:
                        touched_edges.add(pos)
                        edge_saves.append((pos, float(weights[pos])))
                        weights[pos] = INF

            # root_path[:-1] excludes spur_node (root_path's last node), so these
            # row ranges never overlap the individual edge positions blocked above
            # (which all originate from spur_node) — nothing here needs deduping.
            row_saves: list[tuple[int, int, np.ndarray]] = []
            for node in root_path[:-1]:
                start, end = int(indptr[node]), int(indptr[node + 1])
                row_saves.append((start, end, weights[start:end].copy()))
                weights[start:end] = INF

            try:
                spur_result = dijkstra(
                    indptr, indices, weights, source=spur_node, target=target, validate=False
                )
            finally:
                for pos, original in edge_saves:
                    weights[pos] = original
                for start, end, original in row_saves:
                    weights[start:end] = original

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
