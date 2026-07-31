"""Probe placement: sample the corridor at ~1 point per `spacing_m`.

Per CLAUDE.md, we deliberately don't query TomTom once per OSM edge — a
city-scale corridor can have thousands of edges, and the free tier is
20,000 requests/month. Sampling at roughly one probe per ~300m of corridor
length (configurable) cuts API calls by an order of magnitude at
negligible accuracy cost, since travel conditions are highly correlated
between adjacent short edges.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_SPACING_M = 300.0


@dataclass(frozen=True)
class ProbePoint:
    """A sampled edge, ready to be queried against TomTom.

    `u`/`v` are sub-graph node indices of the sampled edge's endpoints;
    `mid_x`/`mid_y` is its midpoint in the same projected CRS as the
    corridor's `x`/`y` arrays.
    """

    u: int
    v: int
    mid_x: float
    mid_y: float


def sample_probe_points(
    indptr: np.ndarray,
    indices: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    spacing_m: float = DEFAULT_SPACING_M,
) -> list[ProbePoint]:
    """Pick edge midpoints roughly every `spacing_m` metres of corridor length.

    Edges are deduplicated by unordered node pair first (a two-way street
    is one physical road, not two independent samples), then visited in a
    fixed (canonical node-pair) order and accumulated by straight-line
    length; a probe is emitted each time the running total crosses another
    multiple of `spacing_m`. This is an approximation (edges aren't walked
    along a continuous route, and edge length is the straight chord between
    endpoints, not the true OSM way geometry) — adequate for deciding how
    densely to sample traffic, not for anything requiring precise distance.
    """
    n = len(indptr) - 1
    seen_pairs: dict[tuple[int, int], tuple[int, int]] = {}
    for u in range(n):
        for pos in range(indptr[u], indptr[u + 1]):
            v = int(indices[pos])
            key = (min(u, v), max(u, v))
            seen_pairs.setdefault(key, (u, v))

    ordered_edges = sorted(seen_pairs.values())

    probes: list[ProbePoint] = []
    cumulative_length = 0.0
    next_threshold = 0.0
    for u, v in ordered_edges:
        edge_length = float(np.hypot(x[u] - x[v], y[u] - y[v]))
        cumulative_length += edge_length
        if cumulative_length >= next_threshold:
            probes.append(ProbePoint(u=u, v=v, mid_x=(x[u] + x[v]) / 2, mid_y=(y[u] + y[v]) / 2))
            next_threshold = cumulative_length + spacing_m

    return probes
