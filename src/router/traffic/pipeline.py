"""Second pass: TomTom-adjusted travel times on the corridor subgraph.

Ties sampling, caching, the TomTom client, and matching into the "traffic"
step of CLAUDE.md's two-pass design. Resilient by construction: any
failure at any stage for a given probe (no API key, a bad response, a
network error, an expired key, a rejected match) just leaves that edge at
its free-flow weight rather than raising — the app must still produce a
route even when traffic data is unavailable, per CLAUDE.md's hard
constraint that it works with no TomTom key at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from router.traffic.cache import TrafficCache
from router.traffic.client import FlowSegment, TomTomAPIError, TomTomClient
from router.traffic.matching import (
    DEFAULT_BUFFER_M,
    DEFAULT_MAX_BEARING_DIFF_DEG,
    edge_matches_segment,
)
from router.traffic.sampling import DEFAULT_SPACING_M, sample_probe_points

ToWgs84 = Callable[[float, float], tuple[float, float]]
ToProjected = Callable[[float, float], tuple[float, float]]

MIN_SPEED_FACTOR = 1e-3


@dataclass(frozen=True)
class TrafficResult:
    """Output of `apply_traffic`.

    `adjusted_weights` is a copy of the input weights with matched edges'
    travel time scaled by `free_flow_speed / current_speed`; unmatched
    edges keep their original (free-flow) weight. `matched_edge_positions`
    are the positions in `adjusted_weights` that got live data.
    """

    adjusted_weights: np.ndarray
    matched_edge_positions: list[int] = field(default_factory=list)
    probes_queried: int = 0
    probes_matched: int = 0

    @property
    def traffic_available(self) -> bool:
        return self.probes_matched > 0


def _edge_position(indptr: np.ndarray, indices: np.ndarray, u: int, v: int) -> int | None:
    for pos in range(indptr[u], indptr[u + 1]):
        if indices[pos] == v:
            return pos
    return None


def apply_traffic(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    to_wgs84: ToWgs84,
    to_projected: ToProjected,
    client: TomTomClient,
    cache: TrafficCache[FlowSegment] | None = None,
    spacing_m: float = DEFAULT_SPACING_M,
    buffer_m: float = DEFAULT_BUFFER_M,
    max_bearing_diff_deg: float = DEFAULT_MAX_BEARING_DIFF_DEG,
) -> TrafficResult:
    """Sample the corridor, fetch/match TomTom data, and adjust travel times.

    `indptr`/`indices`/`weights`/`x`/`y` are the corridor subgraph's own
    arrays (corridor-local node indices, projected coordinates). `to_wgs84`
    converts a projected point to `(lat, lon)` for querying TomTom (which
    only accepts WGS84); `to_projected` is its inverse, used to bring
    TomTom's returned polyline into the same CRS as the corridor for
    matching.
    """
    adjusted_weights = weights.copy()

    if not client.is_available:
        return TrafficResult(adjusted_weights)

    probes = sample_probe_points(indptr, indices, x, y, spacing_m=spacing_m)
    matched_positions: list[int] = []
    matched_count = 0

    for probe in probes:
        segment = cache.get(probe.mid_x, probe.mid_y) if cache is not None else None

        if segment is None:
            lat, lon = to_wgs84(probe.mid_x, probe.mid_y)
            try:
                segment = client.get_flow_segment(lat, lon)
            except TomTomAPIError:
                continue
            if segment is None:
                continue
            if cache is not None:
                cache.set(probe.mid_x, probe.mid_y, segment)

        if segment.road_closure or segment.free_flow_speed_kph <= 0:
            continue

        segment_xy = [to_projected(lat, lon) for lat, lon in segment.coordinates]
        matches = edge_matches_segment(
            x[probe.u],
            y[probe.u],
            x[probe.v],
            y[probe.v],
            segment_xy,
            buffer_m,
            max_bearing_diff_deg,
        )
        if not matches:
            continue

        factor = max(
            min(segment.current_speed_kph / segment.free_flow_speed_kph, 1.0), MIN_SPEED_FACTOR
        )
        matched_count += 1

        # Same physical road in both directions (see module docstring):
        # a dual carriageway's two directions never share a node pair, so
        # this only ever applies to genuinely bidirectional single roads.
        for pos in (
            _edge_position(indptr, indices, probe.u, probe.v),
            _edge_position(indptr, indices, probe.v, probe.u),
        ):
            if pos is not None:
                adjusted_weights[pos] = weights[pos] / factor
                matched_positions.append(pos)

    return TrafficResult(
        adjusted_weights=adjusted_weights,
        matched_edge_positions=matched_positions,
        probes_queried=len(probes),
        probes_matched=matched_count,
    )
