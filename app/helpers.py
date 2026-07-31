"""Pure helper functions for the Streamlit UI.

Kept separate from app/main.py so they're unit-testable without a running
Streamlit/browser session — everything that touches `st.*` or `folium.*`
directly stays in main.py instead.
"""

from __future__ import annotations

import numpy as np

from router.core.geometry import great_circle_distance_m
from router.traffic.pipeline import TrafficResult


def nearest_node(lat: np.ndarray, lon: np.ndarray, point: tuple[float, float]) -> int:
    """Index of the graph node closest to `point` (lat, lon), by great-circle distance."""
    distances = [
        great_circle_distance_m(lat[i], lon[i], point[0], point[1]) for i in range(len(lat))
    ]
    return int(np.argmin(distances))


def path_to_latlon(path: list[int], lat: np.ndarray, lon: np.ndarray) -> list[tuple[float, float]]:
    """A node-index path as a list of `(lat, lon)` points, for folium."""
    return [(float(lat[i]), float(lon[i])) for i in path]


def format_duration(seconds: float) -> str:
    """Human-readable duration: `"45 s"` or `"12 min 30 s"`."""
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs:02d} s"


def format_delta(delta_seconds: float) -> str:
    """Signed human-readable duration delta: `"+2 min 10 s"` or `"-30 s"`."""
    sign = "+" if delta_seconds >= 0 else "-"
    return f"{sign}{format_duration(abs(delta_seconds))}"


def traffic_summary(traffic: TrafficResult) -> str:
    """One-line status of a completed `apply_traffic` call, for the UI."""
    if traffic.probes_queried == 0:
        return "No TomTom API key set — showing free-flow routing only."
    if not traffic.traffic_available:
        return (
            f"Queried {traffic.probes_queried} probes, but none matched a corridor edge — "
            "showing free-flow routing only."
        )
    return f"Live traffic matched {traffic.probes_matched} of {traffic.probes_queried} probes."


def source_node_of_position(indptr: np.ndarray, position: int) -> int:
    """The CSR source-node index whose out-edge range contains `position`."""
    return int(np.searchsorted(indptr, position, side="right") - 1)


def parse_latlon(text: str) -> tuple[float, float] | None:
    """Parse `"lat, lon"` text input, or `None` if it isn't valid."""
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (lat, lon)
