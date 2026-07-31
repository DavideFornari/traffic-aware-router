"""Cache behaviour of load_graph, without hitting the real Overpass API.

Network access is slow and flaky in CI, so `ox.graph_from_bbox` is faked;
what's under test is the cache read/write logic, not osmnx itself.
"""

import networkx as nx

from router.graph import download
from router.graph.config import AreaConfig


def _fake_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_edge(1, 2, travel_time=1.0)
    return g


def _fake_download(calls):
    def _download(*_args, **_kwargs):
        calls.append(1)
        return _fake_graph()

    return _download


def test_cache_miss_downloads_and_writes_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(download.ox, "graph_from_bbox", _fake_download(calls))
    monkeypatch.setattr(download.ox, "save_graphml", lambda g, path: path.write_text("cached"))

    area = AreaConfig(bbox=(10.0, 45.0, 10.1, 45.1))
    download.load_graph(area, cache_dir=tmp_path)

    assert len(calls) == 1
    cache_files = list(tmp_path.glob("*.graphml"))
    assert len(cache_files) == 1


def test_cache_hit_skips_download(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(download.ox, "graph_from_bbox", _fake_download(calls))
    monkeypatch.setattr(download.ox, "save_graphml", lambda g, path: path.write_text("cached"))
    monkeypatch.setattr(download.ox, "load_graphml", lambda path: _fake_graph())

    area = AreaConfig(bbox=(10.0, 45.0, 10.1, 45.1))
    download.load_graph(area, cache_dir=tmp_path)  # populates cache
    download.load_graph(area, cache_dir=tmp_path)  # should hit cache

    assert len(calls) == 1


def test_different_areas_get_different_cache_keys():
    a = AreaConfig(place="Verona, Italy")
    b = AreaConfig(place="Padova, Italy")
    assert download._cache_key(a) != download._cache_key(b)
