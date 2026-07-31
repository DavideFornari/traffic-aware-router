"""Extract an induced sub-CSR graph from a boolean node mask.

Used to restrict Dijkstra/Yen to the corridor (ellipse, then ellipse plus
buffer) instead of the full city-scale graph — the whole point of the
two-pass design (see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Subgraph:
    """Induced subgraph plus the index mapping back to the full graph.

    `sub_to_full[i]` is the full-graph node index for sub-graph index `i`.
    `full_to_sub[j]` is the sub-graph index for full-graph node `j`, or `-1`
    if `j` was excluded by the mask.
    """

    indptr: np.ndarray
    indices: np.ndarray
    weights: np.ndarray
    sub_to_full: np.ndarray
    full_to_sub: np.ndarray

    @property
    def n_nodes(self) -> int:
        return len(self.sub_to_full)

    @property
    def n_edges(self) -> int:
        return len(self.indices)


def extract_subgraph(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    node_mask: np.ndarray,
) -> Subgraph:
    """Induced subgraph on the nodes where `node_mask` is `True`.

    An edge is kept iff both its endpoints are inside the mask. Kept nodes
    are renumbered densely (0..k-1), preserving their relative order from
    the full graph.
    """
    n = len(indptr) - 1
    sub_to_full = np.flatnonzero(node_mask)
    full_to_sub = np.full(n, -1, dtype=np.int64)
    full_to_sub[sub_to_full] = np.arange(len(sub_to_full))

    k = len(sub_to_full)
    out_edges: list[list[tuple[int, float]]] = [[] for _ in range(k)]
    for full_u in sub_to_full:
        su = int(full_to_sub[full_u])
        for pos in range(indptr[full_u], indptr[full_u + 1]):
            sv = int(full_to_sub[indices[pos]])
            if sv != -1:
                out_edges[su].append((sv, weights[pos]))
    for edges in out_edges:
        edges.sort(key=lambda e: e[0])

    n_edges = sum(len(e) for e in out_edges)
    sub_indptr = np.zeros(k + 1, dtype=np.int64)
    sub_indices = np.empty(n_edges, dtype=np.int64)
    sub_weights = np.empty(n_edges, dtype=np.float64)

    pos = 0
    for su in range(k):
        sub_indptr[su] = pos
        for sv, w in out_edges[su]:
            sub_indices[pos] = sv
            sub_weights[pos] = w
            pos += 1
    sub_indptr[k] = pos

    return Subgraph(
        indptr=sub_indptr,
        indices=sub_indices,
        weights=sub_weights,
        sub_to_full=sub_to_full,
        full_to_sub=full_to_sub,
    )
