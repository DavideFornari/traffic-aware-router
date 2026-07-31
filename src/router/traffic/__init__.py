"""TomTom traffic client, probe sampling, polyline matching, TTL cache."""

from router.traffic.cache import TrafficCache
from router.traffic.client import FlowSegment, TomTomAPIError, TomTomClient
from router.traffic.matching import (
    bearing_deg,
    bearing_difference_deg,
    edge_matches_segment,
    local_bearing_deg,
)
from router.traffic.pipeline import TrafficResult, apply_traffic
from router.traffic.sampling import ProbePoint, sample_probe_points

__all__ = [
    "FlowSegment",
    "ProbePoint",
    "TomTomAPIError",
    "TomTomClient",
    "TrafficCache",
    "TrafficResult",
    "apply_traffic",
    "bearing_deg",
    "bearing_difference_deg",
    "edge_matches_segment",
    "local_bearing_deg",
    "sample_probe_points",
]
