"""Golden tests for the prepare step, run on the committed Verona fixture.

No network access: the fixture is a small extract already on disk.
"""

from pathlib import Path

import osmnx as ox
import pytest

from router.graph.prepare import max_speed_kph, prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"


@pytest.fixture
def raw_graph():
    return ox.load_graphml(FIXTURE)


def test_prepare_projects_to_a_metric_crs(raw_graph):
    prepared = prepare_graph(raw_graph)
    crs = prepared.graph["crs"]
    assert "UTM" in str(crs) or "32632" in str(crs)


def test_prepare_adds_speed_and_travel_time_to_every_edge(raw_graph):
    prepared = prepare_graph(raw_graph)
    for _, _, data in prepared.edges(data=True):
        assert data["speed_kph"] > 0
        assert data["travel_time"] > 0


def test_max_speed_kph_is_positive_and_bounds_all_edges(raw_graph):
    prepared = prepare_graph(raw_graph)
    v_max = max_speed_kph(prepared)
    assert v_max > 0
    assert all(data["speed_kph"] <= v_max for _, _, data in prepared.edges(data=True))
