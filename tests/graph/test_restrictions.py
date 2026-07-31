"""Unit tests for turn-restriction fetching and resolution.

No real network calls: `httpx.post` is monkeypatched, matching the style
used for osmnx in test_download.py.
"""

import httpx
import networkx as nx
import pytest

from router.graph.restrictions import (
    RawRestriction,
    _parse_relation,
    fetch_turn_restrictions,
    graph_bbox,
    resolve_restrictions,
)

NO_LEFT_TURN_RELATION = {
    "type": "relation",
    "id": 1,
    "tags": {"type": "restriction", "restriction": "no_left_turn"},
    "members": [
        {"type": "way", "ref": 10, "role": "from"},
        {"type": "node", "ref": 100, "role": "via"},
        {"type": "way", "ref": 20, "role": "to"},
    ],
}

VIA_WAY_RELATION = {
    "type": "relation",
    "id": 2,
    "tags": {"type": "restriction", "restriction": "no_u_turn"},
    "members": [
        {"type": "way", "ref": 10, "role": "from"},
        {"type": "way", "ref": 999, "role": "via"},
        {"type": "way", "ref": 20, "role": "to"},
    ],
}

NOT_A_RESTRICTION = {
    "type": "relation",
    "id": 3,
    "tags": {"type": "route"},
    "members": [],
}


def _small_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_edge(1, 100, key=0, osmid=10)
    g.add_edge(100, 2, key=0, osmid=20)
    g.add_edge(100, 3, key=0, osmid=30)
    return g


def test_parses_a_via_node_restriction():
    raw = _parse_relation(NO_LEFT_TURN_RELATION)
    assert raw == RawRestriction(
        relation_id=1, from_way=10, to_way=20, restriction_type="no_left_turn", via_node=100
    )


def test_parses_a_via_way_restriction():
    raw = _parse_relation(VIA_WAY_RELATION)
    assert raw.via_way == 999
    assert raw.via_node is None


def test_non_restriction_relation_is_skipped():
    assert _parse_relation(NOT_A_RESTRICTION) is None


def test_graph_bbox_from_node_coordinates():
    g = nx.MultiDiGraph()
    g.add_node(1, x=10.0, y=45.0)
    g.add_node(2, x=11.0, y=46.0)
    assert graph_bbox(g) == (45.0, 10.0, 46.0, 11.0)


def test_resolve_via_node_restriction_to_edges():
    raw = _parse_relation(NO_LEFT_TURN_RELATION)
    resolved = resolve_restrictions(_small_graph(), [raw])
    assert len(resolved) == 1
    assert resolved[0].from_edge == (1, 100, 0)
    assert resolved[0].via_node == 100
    assert resolved[0].to_edge == (100, 2, 0)


def test_via_way_restriction_is_not_resolved():
    raw = _parse_relation(VIA_WAY_RELATION)
    assert resolve_restrictions(_small_graph(), [raw]) == []


def test_unmatched_way_id_is_skipped():
    raw = RawRestriction(
        relation_id=4, from_way=999999, to_way=20, restriction_type="no_left_turn", via_node=100
    )
    assert resolve_restrictions(_small_graph(), [raw]) == []


def _fake_response(status_code: int, elements: list[dict]) -> httpx.Response:
    return httpx.Response(
        status_code, json={"elements": elements}, request=httpx.Request("POST", "http://x")
    )


def test_fetch_parses_relations_from_response(monkeypatch):
    def _fake_post(url, data=None, headers=None, timeout=None):
        return _fake_response(200, [NO_LEFT_TURN_RELATION, NOT_A_RESTRICTION])

    monkeypatch.setattr(httpx, "post", _fake_post)

    restrictions = fetch_turn_restrictions(45.0, 10.0, 46.0, 11.0)

    assert len(restrictions) == 1
    assert restrictions[0].restriction_type == "no_left_turn"


def test_fetch_raises_on_http_error(monkeypatch):
    def _fake_post(url, data=None, headers=None, timeout=None):
        return _fake_response(500, [])

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_turn_restrictions(45.0, 10.0, 46.0, 11.0)
