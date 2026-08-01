"""Unit tests for the traffic second pass, with a fake TomTom client.

No real network or real TomTomClient here — a stand-in object with the
same `is_available`/`get_flow_segment` surface, matching the style of the
fake client in scripts/debug_corridor.py's spirit but purpose-built for
tests.
"""

import threading
import time

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


def _long_straight_line_graph(n_edges: int):
    # A chain of n_edges 100m hops along x, long enough that spacing_m=50
    # samples multiple probes per edge — used to exercise real concurrency.
    x = np.array([100.0 * i for i in range(n_edges + 1)])
    y = np.zeros(n_edges + 1)
    indptr = np.array(list(range(n_edges + 1)) + [n_edges])
    indices = np.array(list(range(1, n_edges + 1)))
    weights = np.full(n_edges, 10.0)
    return indptr, indices, weights, x, y


class _ConcurrencyTrackingClient:
    """Records the peak number of `get_flow_segment` calls in flight at
    once, to verify `apply_traffic` actually parallelizes network fetches
    (and respects `max_workers` as a cap) rather than just accepting the
    parameter without using it."""

    is_available = True

    def __init__(self, latency_s: float = 0.05):
        self.latency_s = latency_s
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        self.calls = 0

    def get_flow_segment(self, lat, lon):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.calls += 1
        time.sleep(self.latency_s)
        with self._lock:
            self._active -= 1
        return FlowSegment(
            current_speed_kph=30.0,
            free_flow_speed_kph=60.0,
            current_travel_time_s=0.0,
            free_flow_travel_time_s=0.0,
            confidence=1.0,
            road_closure=False,
            coordinates=[(lat, lon - 1000.0), (lat, lon + 1000.0)],
        )


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


def test_probes_are_fetched_concurrently_up_to_max_workers():
    indptr, indices, weights, x, y = _long_straight_line_graph(n_edges=20)
    client = _ConcurrencyTrackingClient(latency_s=0.05)

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
        max_workers=4,
    )

    assert client.calls > 4  # enough probes that a real cap is exercised
    assert 1 < client.max_active <= 4
    assert result.probes_matched == client.calls


def test_max_workers_of_one_fetches_strictly_sequentially():
    indptr, indices, weights, x, y = _long_straight_line_graph(n_edges=20)
    client = _ConcurrencyTrackingClient(latency_s=0.02)

    apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        client,
        spacing_m=50.0,
        max_workers=1,
    )

    assert client.max_active == 1


def test_parallel_fetch_result_matches_sequential_result():
    # Concurrency must not change *what* gets matched/adjusted, only how
    # fast the fetches happen — compare max_workers=1 (effectively the old
    # sequential behaviour) against a parallel run on the same graph.
    indptr, indices, weights, x, y = _long_straight_line_graph(n_edges=20)

    sequential = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        _FakeClient(current_speed=30.0, free_flow_speed=60.0),
        spacing_m=50.0,
        max_workers=1,
    )
    parallel = apply_traffic(
        indptr,
        indices,
        weights,
        x,
        y,
        _identity_to_wgs84,
        _identity_to_projected,
        _FakeClient(current_speed=30.0, free_flow_speed=60.0),
        spacing_m=50.0,
        max_workers=8,
    )

    assert sequential.probes_queried == parallel.probes_queried
    assert sequential.probes_matched == parallel.probes_matched
    assert sequential.matched_edge_positions == parallel.matched_edge_positions
    np.testing.assert_array_equal(sequential.adjusted_weights, parallel.adjusted_weights)
