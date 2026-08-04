"""Golden tests for the prepare step, run on the committed Verona fixture.

No network access: the fixture is a small extract already on disk.
"""

from pathlib import Path

import networkx as nx
import osmnx as ox
import pytest

from router.graph.prepare import max_speed_kph, prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"


def _hand_built_graph_with_motorway():
    # Three edges of increasing speed; the fastest is tagged as a motorway,
    # so exclude_motorway should drop it from consideration entirely.
    g = nx.MultiDiGraph()
    g.add_edge(0, 1, highway="residential", speed_kph=30.0)
    g.add_edge(1, 2, highway="tertiary", speed_kph=50.0)
    g.add_edge(2, 3, highway="motorway", speed_kph=130.0)
    return g


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


def test_max_speed_kph_default_is_the_true_max():
    assert max_speed_kph(_hand_built_graph_with_motorway()) == 130.0


def test_max_speed_kph_exclude_motorway_drops_the_fastest_edge():
    v_max = max_speed_kph(_hand_built_graph_with_motorway(), exclude_motorway=True)
    assert v_max == 50.0


def test_max_speed_kph_exclude_motorway_matches_list_tagged_edges():
    g = nx.MultiDiGraph()
    g.add_edge(0, 1, highway=["residential", "motorway_link"], speed_kph=130.0)
    g.add_edge(1, 2, highway="residential", speed_kph=30.0)
    assert max_speed_kph(g, exclude_motorway=True) == 30.0


def test_max_speed_kph_exclude_motorway_raises_if_nothing_remains():
    g = nx.MultiDiGraph()
    g.add_edge(0, 1, highway="motorway", speed_kph=130.0)
    with pytest.raises(ValueError):
        max_speed_kph(g, exclude_motorway=True)


def test_max_speed_kph_percentile_is_at_most_the_true_max(raw_graph):
    prepared = prepare_graph(raw_graph)
    v_max = max_speed_kph(prepared)
    v_p50 = max_speed_kph(prepared, percentile=50)
    assert 0 < v_p50 <= v_max


def test_max_speed_kph_percentile_100_equals_max():
    g = _hand_built_graph_with_motorway()
    assert max_speed_kph(g, percentile=100) == pytest.approx(max_speed_kph(g))
