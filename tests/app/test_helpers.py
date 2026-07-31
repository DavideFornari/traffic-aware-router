"""Unit tests for app/helpers.py — the UI's pure, Streamlit-free logic."""

import numpy as np
import pytest

from app.helpers import (
    format_delta,
    format_duration,
    nearest_node,
    parse_latlon,
    path_to_latlon,
    source_node_of_position,
    traffic_summary,
)
from router.traffic.pipeline import TrafficResult


def test_nearest_node_picks_the_closest_point():
    lat = np.array([45.0, 45.1, 46.0])
    lon = np.array([10.0, 10.0, 10.0])
    assert nearest_node(lat, lon, (45.09, 10.0)) == 1


def test_path_to_latlon_pairs_coordinates_in_path_order():
    lat = np.array([1.0, 2.0, 3.0])
    lon = np.array([10.0, 20.0, 30.0])
    assert path_to_latlon([2, 0], lat, lon) == [(3.0, 30.0), (1.0, 10.0)]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 s"), (45, "45 s"), (59.9, "60 s"), (60, "1 min 00 s"), (750, "12 min 30 s")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_delta_signs_positive_and_negative():
    assert format_delta(130) == "+2 min 10 s"
    assert format_delta(-45) == "-45 s"
    assert format_delta(0) == "+0 s"


def test_source_node_of_position_maps_back_to_the_owning_row():
    indptr = np.array([0, 2, 3, 3])
    assert [source_node_of_position(indptr, p) for p in range(3)] == [0, 0, 1]


def test_traffic_summary_no_key():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=0, probes_matched=0)
    assert "No TomTom API key" in traffic_summary(result)


def test_traffic_summary_no_matches():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=5, probes_matched=0)
    assert "none matched" in traffic_summary(result)


def test_traffic_summary_with_matches():
    result = TrafficResult(adjusted_weights=np.array([]), probes_queried=5, probes_matched=3)
    assert traffic_summary(result) == "Live traffic matched 3 of 5 probes."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45.43, 10.99", (45.43, 10.99)),
        ("45.43,10.99", (45.43, 10.99)),
        ("not a coordinate", None),
        ("200, 10", None),
        ("45.43", None),
    ],
)
def test_parse_latlon(text, expected):
    assert parse_latlon(text) == expected
