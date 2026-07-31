"""Fetch and resolve OSM turn-restriction relations via the Overpass API.

OSM encodes a banned (or mandatory) turn as a `type=restriction` relation
between a `from` way, a `via` node (or way), and a `to` way — not as a
property of any single edge — and osmnx does not fetch or apply these.
This module fetches them separately and maps each relation's members onto
concrete edges of an already-downloaded graph, for the line-graph adapter
(`line_graph.py`) to apply.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import networkx as nx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_TIMEOUT_S = 180.0
USER_AGENT = "traffic-aware-router (https://github.com/DavideFornari/traffic-aware-router)"


@dataclass(frozen=True)
class RawRestriction:
    """A `type=restriction` relation as reported by Overpass, unresolved.

    `via_node`/`via_way` are mutually exclusive depending on the relation's
    `via` member type — most restrictions use a single via node; a via way
    (used for some `no_u_turn` geometries) is not resolved by this module
    (see `resolve_restrictions`).
    """

    relation_id: int
    from_way: int
    to_way: int
    restriction_type: str
    via_node: int | None = None
    via_way: int | None = None


@dataclass(frozen=True)
class TurnRestriction:
    """A restriction resolved to concrete edges of a specific graph."""

    from_edge: tuple[int, int, int]
    via_node: int
    to_edge: tuple[int, int, int]
    restriction_type: str


def graph_bbox(graph: nx.MultiDiGraph) -> tuple[float, float, float, float]:
    """`(south, west, north, east)` bounding box of `graph`'s (unprojected) nodes."""
    lats = [data["y"] for _, data in graph.nodes(data=True)]
    lons = [data["x"] for _, data in graph.nodes(data=True)]
    return min(lats), min(lons), max(lats), max(lons)


def fetch_turn_restrictions(
    south: float,
    west: float,
    north: float,
    east: float,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[RawRestriction]:
    """Fetch `type=restriction` relations within the given bounding box."""
    query = f"""
    [out:json][timeout:{int(timeout_s)}];
    relation["type"="restriction"]({south},{west},{north},{east});
    out body;
    """
    response = httpx.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_s,
    )
    response.raise_for_status()

    restrictions = []
    for element in response.json()["elements"]:
        if element.get("type") != "relation":
            continue
        raw = _parse_relation(element)
        if raw is not None:
            restrictions.append(raw)
    return restrictions


def _parse_relation(element: dict) -> RawRestriction | None:
    tags = element.get("tags", {})
    restriction_type = tags.get("restriction")
    if restriction_type is None:
        return None

    from_way = to_way = via_node = via_way = None
    for member in element.get("members", []):
        role = member.get("role")
        if role == "from" and member.get("type") == "way":
            from_way = member["ref"]
        elif role == "to" and member.get("type") == "way":
            to_way = member["ref"]
        elif role == "via" and member.get("type") == "node":
            via_node = member["ref"]
        elif role == "via" and member.get("type") == "way":
            via_way = member["ref"]

    if from_way is None or to_way is None or (via_node is None and via_way is None):
        return None

    return RawRestriction(
        relation_id=element["id"],
        from_way=from_way,
        to_way=to_way,
        restriction_type=restriction_type,
        via_node=via_node,
        via_way=via_way,
    )


def _edge_ways(data: dict) -> set[int]:
    osmid = data.get("osmid")
    if osmid is None:
        return set()
    return set(osmid) if isinstance(osmid, list) else {osmid}


def _find_edge_ending_at(
    graph: nx.MultiDiGraph, way_id: int, node: int
) -> tuple[int, int, int] | None:
    if node not in graph:
        return None
    for u, _, key, data in graph.in_edges(node, keys=True, data=True):
        if way_id in _edge_ways(data):
            return (u, node, key)
    return None


def _find_edge_starting_at(
    graph: nx.MultiDiGraph, way_id: int, node: int
) -> tuple[int, int, int] | None:
    if node not in graph:
        return None
    for _, v, key, data in graph.out_edges(node, keys=True, data=True):
        if way_id in _edge_ways(data):
            return (node, v, key)
    return None


def resolve_restrictions(
    graph: nx.MultiDiGraph, raw_restrictions: list[RawRestriction]
) -> list[TurnRestriction]:
    """Map each restriction's `from`/`via`/`to` members onto `graph`'s edges.

    Restrictions via a way (rather than a node) are skipped: resolving them
    would need splitting that way into the specific edge sequence the
    relation implies, which this project doesn't attempt (documented
    limitation, not a silent gap — see the README). A restriction is also
    skipped if its via node isn't in `graph` at all, or its from/to way
    isn't found incident to the via node — both happen when the relation
    refers to an OSM node or way that osmnx simplified, merged, or dropped
    (e.g. it fell just outside the graph's bbox) when building the graph.
    """
    resolved = []
    for raw in raw_restrictions:
        if raw.via_node is None:
            continue

        from_edge = _find_edge_ending_at(graph, raw.from_way, raw.via_node)
        to_edge = _find_edge_starting_at(graph, raw.to_way, raw.via_node)
        if from_edge is None or to_edge is None:
            continue

        resolved.append(
            TurnRestriction(
                from_edge=from_edge,
                via_node=raw.via_node,
                to_edge=to_edge,
                restriction_type=raw.restriction_type,
            )
        )
    return resolved
