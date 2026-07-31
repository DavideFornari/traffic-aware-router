"""Download and disk-cache OSM road networks via osmnx.

Downloading is the slow, network-dependent, rate-limited step, so every
graph pulled from the Overpass API is cached to disk as GraphML, keyed by a
hash of the area configuration. Re-running with the same config is instant
and works offline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import networkx as nx
import osmnx as ox

from router.graph.config import AreaConfig

DEFAULT_CACHE_DIR = Path("data/cache/graphs")


def _cache_key(area: AreaConfig) -> str:
    raw = f"{area.place}|{area.bbox}|{area.network_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_graph(area: AreaConfig, cache_dir: Path = DEFAULT_CACHE_DIR) -> nx.MultiDiGraph:
    """Return the raw (unprojected) OSM network for `area`.

    Reads from `cache_dir` if a matching cached extract exists; otherwise
    downloads via the Overpass API and writes the cache for next time.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_cache_key(area)}.graphml"

    if cache_path.exists():
        return ox.load_graphml(cache_path)

    if area.bbox is not None:
        graph = ox.graph_from_bbox(area.bbox, network_type=area.network_type)
    else:
        graph = ox.graph_from_place(area.place, network_type=area.network_type)

    ox.save_graphml(graph, cache_path)
    return graph
