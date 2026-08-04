"""Project a raw OSM graph and attach free-flow speeds and travel times.

All later geometric reasoning (ellipse, buffers, matching) must happen in a
projected metric CRS, never in raw lat/lon degrees — projection happens once,
here, right after download.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import osmnx as ox


def prepare_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Project to the area's UTM zone and add imputed speeds and travel times.

    Missing `maxspeed` is imputed by `add_edge_speeds` as the mean of known
    speeds per highway type. This is optimistic for residential streets,
    whose real-world speeds tend to run below that average — noted here
    since it directly biases free-flow routing towards residential shortcuts.

    Original lat/lon is stashed as `lat`/`lon` node attributes before
    projection overwrites `y`/`x` with projected metres: the A* heuristic
    (Milestone 3) needs great-circle distance, which requires unprojected
    coordinates, even though everything else operates in the metric CRS.
    """
    for _, data in graph.nodes(data=True):
        data["lat"] = data["y"]
        data["lon"] = data["x"]

    projected = ox.project_graph(graph)
    projected = ox.add_edge_speeds(projected)
    projected = ox.add_edge_travel_times(projected)
    return projected


def _is_motorway(data: dict) -> bool:
    """True if an edge's `highway` tag is `motorway` or `motorway_link`.

    OSM's `highway` tag is a single string or (when osmnx has multiple raw
    ways collapsed into one edge) a list of strings — check both shapes.
    """
    highway = data.get("highway", "")
    tags = highway if isinstance(highway, list) else [highway]
    return any(tag in ("motorway", "motorway_link") for tag in tags)


def max_speed_kph(
    graph: nx.MultiDiGraph,
    percentile: float | None = None,
    exclude_motorway: bool = False,
) -> float:
    """Edge speed present in `graph` used as `v_max` for the corridor ellipse bound.

    By default (`percentile=None`, `exclude_motorway=False`) this is the true
    maximum imputed edge speed anywhere in `graph`, in km/h: a route optimal
    in free-flow time cannot cover more distance than time times this top
    speed, which is what makes `ellipse_l_max` a *proven* bound (see
    CLAUDE.md and README's Corridor section) — no edge in the graph, however
    far from the trip, exceeds it.

    `percentile` (e.g. `95`) and `exclude_motorway=True` both relax that:
    they can make `v_max` lower than some edge actually in the graph, so a
    free-flow-optimal route that genuinely needs a faster edge (the
    excluded motorway, or the top few percent of speeds) could in principle
    be excluded from the ellipse. This trades the containment proof for a
    smaller, faster corridor — offered as an explicit, labelled choice in
    the UI's ellipse-mode toggle, never silently substituted for the
    default. See the "not a bug" note in README's Corridor section for why
    the strict default is loose for city extracts that include a motorway.
    """
    edges = graph.edges(data=True)
    if exclude_motorway:
        edges = ((u, v, data) for u, v, data in edges if not _is_motorway(data))
    speeds = [data["speed_kph"] for _, _, data in edges]
    if not speeds:
        raise ValueError("No edges remain after filtering (exclude_motorway removed all edges?).")
    if percentile is None:
        return max(speeds)
    return float(np.percentile(speeds, percentile))
