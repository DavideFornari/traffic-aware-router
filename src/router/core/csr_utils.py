"""Small shared helpers over CSR arrays, used by more than one core/traffic module."""

from __future__ import annotations

import numpy as np


def edge_position(indptr: np.ndarray, indices: np.ndarray, u: int, v: int) -> int | None:
    """Position in `indices`/`weights` of the edge `u -> v`, or `None` if absent.

    Each node's out-edges are sorted by target index (see `CSRGraph`'s
    docstring and `Subgraph.indices`), so a binary search per lookup
    replaces a linear scan of the row.
    """
    row_start, row_end = indptr[u], indptr[u + 1]
    row = indices[row_start:row_end]
    offset = np.searchsorted(row, v)
    if offset < len(row) and row[offset] == v:
        return int(row_start + offset)
    return None
