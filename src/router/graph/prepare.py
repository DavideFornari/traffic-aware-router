"""Project a raw OSM graph and attach free-flow speeds and travel times.

All later geometric reasoning (ellipse, buffers, matching) must happen in a
projected metric CRS, never in raw lat/lon degrees — projection happens once,
here, right after download.
"""

from __future__ import annotations

import networkx as nx
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


def max_speed_kph(graph: nx.MultiDiGraph) -> float:
    """Maximum imputed edge speed present in `graph`, in km/h.

    This is `v_max` for the corridor ellipse bound: a route optimal in
    free-flow time cannot cover more distance than time times this top
    speed, which is what bounds the ellipse's major axis (see CLAUDE.md).
    """
    return max(data["speed_kph"] for _, _, data in graph.edges(data=True))
