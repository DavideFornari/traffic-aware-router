"""Unit tests for the traffic second pass, with a fake TomTom client.

No real network or real TomTomClient here — a stand-in object with the
same `is_available`/`get_flow_segment` surface, matching the style of the
fake client in scripts/debug_corridor.py's spirit but purpose-built for
tests.
"""

import numpy as np
import pytest

from router.traffic.cache import TrafficCache
from router.traffic.client import FlowSegment
from router.traffic.pipeline import apply_traffic


class _UnavailableClient:
    is_available = False

    def get_flow_segment(self, lat, lon):
        raise AssertionError("should never be called when unavailable")


class _FakeClient:
    """Reports a segment centred on the queried point, running along +x —
    aligned with (and covering) whichever edge was actually probed, since
    `_identity_to_wgs84`/`_identity_to_projected` map lon <-> x directly."""

    is_available = True

    def __init__(self, current_speed=30.0, free_flow_speed=60.0, road_closure=False):
        self.current_speed = current_speed
        self.free_flow_speed = free_flow_speed
        self.road_closure = road_closure
        self.calls = 0

    def get_flow_segment(self, lat, lon):
        self.calls += 1
        return FlowSegment(
            current_speed_kph=self.current_speed,
            free_flow_speed_kph=self.free_flow_speed,
            current_travel_time_s=0.0,
            free_flow_travel_time_s=0.0,
            confidence=1.0,
            road_closure=self.road_closure,
            coordinates=[(lat, lon - 1000.0), (lat, lon + 1000.0)],
        )


def _identity_to_wgs84(x, y):
    return (0.0, x)  # lat is unused by the fake client; lon carries x through


def _identity_to_projected(lat, lon):
    return (lon, 0.0)


def _straight_line_graph():
    # 0 -> 1 -> 2, 100m each hop, collinear along x, aligned with the
    # fake segment's bearing (segment matches edges running along +x).
    x = np.array([0.0, 100.0, 200.0])
    y = np.array([0.0, 0.0, 0.0])
    indptr = np.array([0, 1, 2, 2])
    indices = np.array([1, 2])
    weights = np.array([10.0, 10.0])
    return indptr, indices, weights, x, y


def test_no_client_available_returns_unchanged_weights():
    indptr, indices, weights, x, y = _straight_line_graph()
    result = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        _UnavailableClient(),
    )
    np.testing.assert_array_equal(result.adjusted_weights, weights)
    assert not result.traffic_available
    assert result.probes_queried == 0


def test_matched_edges_get_slowed_down_proportionally():
    indptr, indices, weights, x, y = _straight_line_graph()
    client = _FakeClient(current_speed=30.0, free_flow_speed=60.0)

    result = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        spacing_m=50.0,
    )

    assert result.traffic_available
    # factor = 30/60 = 0.5, so travel time doubles on matched edges.
    assert np.all(result.adjusted_weights[result.matched_edge_positions] == pytest.approx(20.0))


def test_road_closure_is_not_matched():
    indptr, indices, weights, x, y = _straight_line_graph()
    client = _FakeClient(road_closure=True)

    result = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        spacing_m=50.0,
    )

    assert not result.traffic_available
    np.testing.assert_array_equal(result.adjusted_weights, weights)


def test_unmatched_edges_keep_free_flow_weight():
    indptr, indices, weights, x, y = _straight_line_graph()
    client = _FakeClient()

    result = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        spacing_m=50.0,
    )

    unmatched = [p for p in range(len(weights)) if p not in result.matched_edge_positions]
    for pos in unmatched:
        assert result.adjusted_weights[pos] == weights[pos]


def test_cache_avoids_a_second_network_call_for_the_same_probe():
    indptr, indices, weights, x, y = _straight_line_graph()
    client = _FakeClient()
    cache = TrafficCache[FlowSegment]()

    apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        cache=cache,
        spacing_m=50.0,
    )
    calls_after_first = client.calls
    apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        cache=cache,
        spacing_m=50.0,
    )

    assert client.calls == calls_after_first


def test_never_scales_weight_by_more_than_free_flow_speed_ratio():
    # a bogus current_speed > free_flow_speed shouldn't speed up an edge
    # past its free-flow weight (factor is clipped to at most 1.0).
    indptr, indices, weights, x, y = _straight_line_graph()
    client = _FakeClient(current_speed=90.0, free_flow_speed=60.0)

    result = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        spacing_m=50.0,
    )

    assert np.all(result.adjusted_weights >= weights - 1e-9)
