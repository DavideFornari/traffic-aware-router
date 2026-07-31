"""Tests for turn-restriction-aware corridor routing (CLAUDE.md P1 #1)."""

from pathlib import Path

import numpy as np
import osmnx as ox
import pytest

from router.core.dijkstra import dijkstra
from router.corridor.pipeline import build_corridor
from router.corridor.restricted_second_pass import (
    corridor_line_graph,
    route_corridor_second_pass,
)
from router.graph.csr import build_csr
from router.graph.prepare import max_speed_kph, prepare_graph
from router.graph.restrictions import TurnRestriction

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"
SOURCE_ID = 30691468
TARGET_ID = 12730614170


@pytest.fixture(scope="module")
def csr_and_corridor():
    raw = ox.load_graphml(FIXTURE)
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max = max_speed_kph(graph) * 1000 / 3600

    origin = int(np.searchsorted(csr.node_ids, SOURCE_ID))
    destination = int(np.searchsorted(csr.node_ids, TARGET_ID))
    corridor = build_corridor(
        csr.indptr,
        csr.indices,
        csr.weights,
        csr.x,
        csr.y,
        origin,
        destination,
        v_max,
        edge_keys=csr.edge_keys,
    )
    return csr, corridor, origin, destination


def _corridor_local_arrays(csr, corridor):
    idx = corridor.subgraph.sub_to_full
    return csr.node_ids[idx], csr.lat[idx], csr.lon[idx], csr.x[idx], csr.y[idx]


def test_corridor_carries_edge_keys_when_requested(csr_and_corridor):
    _, corridor, _, _ = csr_and_corridor
    assert corridor.subgraph.edge_keys is not None
    assert len(corridor.subgraph.edge_keys) == corridor.subgraph.n_edges


def test_build_corridor_without_edge_keys_leaves_it_none():
    # extract_subgraph's default behaviour is unaffected — only opting in
    # (build_corridor's new edge_keys= param) changes anything.
    indptr = np.array([0, 1, 1])
    indices = np.array([1])
    weights = np.array([1.0])
    x = np.array([0.0, 100.0])
    y = np.array([0.0, 0.0])
    from router.corridor.pipeline import build_corridor as _build_corridor

    corridor = _build_corridor(indptr, indices, weights, x, y, 0, 1, v_max=10.0)
    assert corridor.subgraph.edge_keys is None


def test_corridor_line_graph_requires_edge_keys():
    from router.corridor.subgraph import Subgraph

    bare = Subgraph(
        indptr=np.array([0, 0]),
        indices=np.array([], dtype=np.int64),
        weights=np.array([]),
        sub_to_full=np.array([0]),
        full_to_sub=np.array([0]),
    )
    with pytest.raises(ValueError, match="edge_keys"):
        corridor_line_graph(
            bare,
            np.array([1]),
            np.array([0.0]),
            np.array([0.0]),
            np.array([0.0]),
            np.array([0.0]),
            np.array([]),
        )


def test_unrestricted_second_pass_matches_plain_node_dijkstra(csr_and_corridor):
    csr, corridor, origin, destination = csr_and_corridor
    real_node_ids, lat, lon, x, y = _corridor_local_arrays(csr, corridor)

    result = route_corridor_second_pass(
        corridor.subgraph,
        real_node_ids,
        lat,
        lon,
        x,
        y,
        corridor.subgraph.weights,
        SOURCE_ID,
        TARGET_ID,
    )
    assert result is not None
    path, cost = result
    assert path[0] == SOURCE_ID
    assert path[-1] == TARGET_ID

    sub_origin = int(corridor.subgraph.full_to_sub[origin])
    sub_destination = int(corridor.subgraph.full_to_sub[destination])
    plain = dijkstra(
        corridor.subgraph.indptr,
        corridor.subgraph.indices,
        corridor.subgraph.weights,
        sub_origin,
        sub_destination,
    )
    assert cost == pytest.approx(float(plain.dist[sub_destination]), rel=1e-6)


def test_banning_the_first_turn_forces_a_reroute_or_failure(csr_and_corridor):
    csr, corridor, origin, destination = csr_and_corridor
    real_node_ids, lat, lon, x, y = _corridor_local_arrays(csr, corridor)

    unrestricted = route_corridor_second_pass(
        corridor.subgraph,
        real_node_ids,
        lat,
        lon,
        x,
        y,
        corridor.subgraph.weights,
        SOURCE_ID,
        TARGET_ID,
    )
    assert unrestricted is not None
    unrestricted_path, unrestricted_cost = unrestricted

    ban = TurnRestriction(
        from_edge=(unrestricted_path[0], unrestricted_path[1], 0),
        via_node=unrestricted_path[1],
        to_edge=(unrestricted_path[1], unrestricted_path[2], 0),
        restriction_type="no_left_turn",
    )
    restricted = route_corridor_second_pass(
        corridor.subgraph,
        real_node_ids,
        lat,
        lon,
        x,
        y,
        corridor.subgraph.weights,
        SOURCE_ID,
        TARGET_ID,
        restrictions=[ban],
    )

    # Banning a turn can only make the route as good or worse, never better,
    # and if there IS still a route, it must not use the banned maneuver.
    if restricted is not None:
        restricted_path, restricted_cost = restricted
        assert restricted_cost >= unrestricted_cost - 1e-6
        assert restricted_path[:3] != unrestricted_path[:3]


def test_traffic_adjusted_weights_flow_through_to_the_line_graph(csr_and_corridor):
    # A weights array distinct from the corridor's own (as apply_traffic
    # would produce) must be what the line graph — and therefore the
    # route's cost — actually uses, not silently falling back to free-flow.
    csr, corridor, origin, destination = csr_and_corridor
    real_node_ids, lat, lon, x, y = _corridor_local_arrays(csr, corridor)

    inflated_weights = corridor.subgraph.weights * 10.0

    free_flow_result = route_corridor_second_pass(
        corridor.subgraph,
        real_node_ids,
        lat,
        lon,
        x,
        y,
        corridor.subgraph.weights,
        SOURCE_ID,
        TARGET_ID,
    )
    inflated_result = route_corridor_second_pass(
        corridor.subgraph,
        real_node_ids,
        lat,
        lon,
        x,
        y,
        inflated_weights,
        SOURCE_ID,
        TARGET_ID,
    )

    assert free_flow_result is not None
    assert inflated_result is not None
    assert inflated_result[1] == pytest.approx(free_flow_result[1] * 10.0, rel=1e-6)
