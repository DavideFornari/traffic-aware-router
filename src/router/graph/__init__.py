"""OSM download, caching, and adapters from networkx graphs to CSR arrays."""

from router.graph.config import AreaConfig, verona
from router.graph.csr import CSRGraph, build_csr
from router.graph.download import load_graph
from router.graph.line_graph import build_line_graph, find_line_node, source_edge_weight
from router.graph.prepare import max_speed_kph, prepare_graph
from router.graph.restrictions import (
    RawRestriction,
    TurnRestriction,
    fetch_turn_restrictions,
    graph_bbox,
    resolve_restrictions,
)

__all__ = [
    "AreaConfig",
    "CSRGraph",
    "RawRestriction",
    "TurnRestriction",
    "build_csr",
    "build_line_graph",
    "fetch_turn_restrictions",
    "find_line_node",
    "graph_bbox",
    "load_graph",
    "max_speed_kph",
    "prepare_graph",
    "resolve_restrictions",
    "source_edge_weight",
    "verona",
]
