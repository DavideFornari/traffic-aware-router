"""Golden test: the traffic second pass on the real corridor from the
committed Verona fixture, with a fake TomTom client (no network)."""

from pathlib import Path

import numpy as np
import osmnx as ox
import pytest
from pyproj import Transformer

from router.core.dijkstra import dijkstra
from router.corridor.pipeline import build_corridor
from router.graph.csr import build_csr
from router.graph.prepare import max_speed_kph, prepare_graph
from router.traffic.client import FlowSegment
from router.traffic.pipeline import apply_traffic

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"

ORIGIN_ID = 30691468
DESTINATION_ID = 12730614170


class _AlwaysCongestedClient:
    """Reports every road as at half its free-flow speed."""

    is_available = True

    def get_flow_segment(self, lat, lon):
        return FlowSegment(
            current_speed_kph=1.0,
            free_flow_speed_kph=2.0,
            current_travel_time_s=0.0,
            free_flow_travel_time_s=0.0,
            confidence=1.0,
            road_closure=False,
            coordinates=[(lat - 0.01, lon - 0.01), (lat + 0.01, lon + 0.01)],
        )


@pytest.fixture(scope="module")
def corridor_and_transform():
    raw = ox.load_graphml(FIXTURE)
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600

    origin = int(np.searchsorted(csr.node_ids, ORIGIN_ID))
    destination = int(np.searchsorted(csr.node_ids, DESTINATION_ID))

    result = build_corridor(
        csr.indptr, csr.indices, csr.weights, csr.x, csr.y, origin, destination, v_max_mps
    )
    to_wgs84 = Transformer.from_crs(graph.graph["crs"], "EPSG:4326", always_xy=True)
    to_projected = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True)

    sub_origin = int(result.subgraph.full_to_sub[origin])
    sub_destination = int(result.subgraph.full_to_sub[destination])
    sub_x = csr.x[result.subgraph.sub_to_full]
    sub_y = csr.y[result.subgraph.sub_to_full]

    return result, sub_x, sub_y, sub_origin, sub_destination, to_wgs84, to_projected


def _wgs84_fn(transformer):
    return lambda x, y: transformer.transform(x, y)[::-1]


def _projected_fn(transformer):
    return lambda lat, lon: transformer.transform(lon, lat)


def test_traffic_pass_never_speeds_up_the_route(corridor_and_transform):
    result, sub_x, sub_y, sub_origin, sub_destination, to_wgs84_t, to_projected_t = (
        corridor_and_transform
    )

    traffic = apply_traffic(
        result.subgraph.indptr,
        result.subgraph.indices,
        result.subgraph.weights,
        sub_x,
        sub_y,
        _wgs84_fn(to_wgs84_t),
        _projected_fn(to_projected_t),
        _AlwaysCongestedClient(),
    )

    assert traffic.traffic_available
    assert np.all(traffic.adjusted_weights >= result.subgraph.weights - 1e-9)


def test_traffic_aware_route_is_never_faster_than_free_flow(corridor_and_transform):
    result, sub_x, sub_y, sub_origin, sub_destination, to_wgs84_t, to_projected_t = (
        corridor_and_transform
    )

    traffic = apply_traffic(
        result.subgraph.indptr,
        result.subgraph.indices,
        result.subgraph.weights,
        sub_x,
        sub_y,
        _wgs84_fn(to_wgs84_t),
        _projected_fn(to_projected_t),
        _AlwaysCongestedClient(),
    )

    free_flow = dijkstra(
        result.subgraph.indptr,
        result.subgraph.indices,
        result.subgraph.weights,
        sub_origin,
        sub_destination,
    )
    traffic_aware = dijkstra(
        result.subgraph.indptr,
        result.subgraph.indices,
        traffic.adjusted_weights,
        sub_origin,
        sub_destination,
    )

    assert traffic_aware.dist[sub_destination] >= free_flow.dist[sub_destination] - 1e-6


def test_no_client_leaves_route_identical_to_free_flow(corridor_and_transform):
    result, sub_x, sub_y, sub_origin, sub_destination, to_wgs84_t, to_projected_t = (
        corridor_and_transform
    )

    class _Unavailable:
        is_available = False

    traffic = apply_traffic(
        result.subgraph.indptr,
        result.subgraph.indices,
        result.subgraph.weights,
        sub_x,
        sub_y,
        _wgs84_fn(to_wgs84_t),
        _projected_fn(to_projected_t),
        _Unavailable(),
    )

    np.testing.assert_array_equal(traffic.adjusted_weights, result.subgraph.weights)
    assert not traffic.traffic_available
