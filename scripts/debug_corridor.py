"""Render the corridor (ellipse, Yen's k paths, buffer, final subgraph) on a map.

A visual sanity check for Milestone 4: the ellipse bound and the buffered
union are the fiddliest geometry in the corridor step, and eyeballing them
on a real map catches mistakes that unit tests on synthetic coordinates
would miss (e.g. picking the wrong CRS, or an inverted ellipse test).

Requires the `viz` extra: `pip install -e ".[viz]"`.

Usage: python scripts/debug_corridor.py [--place "Verona, Italy"]
                                         [--origin LAT,LON] [--destination LAT,LON]
                                         [--epsilon 0.3] [--k 4] [--buffer-m 200]
                                         [--out corridor_debug.html]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import folium
import numpy as np
from pyproj import Transformer

from router.core.geometry import great_circle_distance_m
from router.corridor.pipeline import build_corridor
from router.graph.config import AreaConfig
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.prepare import max_speed_kph, prepare_graph

# Piazza Bra to Stadio Marc'Antonio Bentegodi — a real cross-town route.
DEFAULT_ORIGIN = (45.4384, 10.9916)
DEFAULT_DESTINATION = (45.4353, 10.9548)

PATH_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def _nearest_node(lat: np.ndarray, lon: np.ndarray, point: tuple[float, float]) -> int:
    distances = [
        great_circle_distance_m(lat[i], lon[i], point[0], point[1]) for i in range(len(lat))
    ]
    return int(np.argmin(distances))


def _parse_latlon(s: str) -> tuple[float, float]:
    lat_str, lon_str = s.split(",")
    return float(lat_str), float(lon_str)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", default="Verona, Italy")
    parser.add_argument("--origin", type=_parse_latlon, default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", type=_parse_latlon, default=DEFAULT_DESTINATION)
    parser.add_argument("--epsilon", type=float, default=0.3)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--buffer-m", type=float, default=200.0)
    parser.add_argument("--out", default="corridor_debug.html")
    args = parser.parse_args()

    print(f"Loading and preparing {args.place!r}...")
    raw = load_graph(AreaConfig(place=args.place))
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600

    origin = _nearest_node(csr.lat, csr.lon, args.origin)
    destination = _nearest_node(csr.lat, csr.lon, args.destination)
    print(f"Origin node: {csr.node_ids[origin]}, destination node: {csr.node_ids[destination]}")

    result = build_corridor(
        csr.indptr,
        csr.indices,
        csr.weights,
        csr.x,
        csr.y,
        origin,
        destination,
        v_max_mps,
        epsilon=args.epsilon,
        k=args.k,
        buffer_m=args.buffer_m,
    )
    print(f"t_star = {result.t_star:.1f}s, l_max = {result.l_max:.0f}m")
    print(f"Corridor: {result.subgraph.n_nodes} of {csr.n_nodes} nodes")
    print(f"Candidate path costs: {[round(c, 1) for c in result.candidate_costs]}")

    to_wgs84 = Transformer.from_crs(graph.graph["crs"], "EPSG:4326", always_xy=True)

    m = folium.Map(location=list(args.origin), zoom_start=14, tiles="cartodbpositron")

    folium.Marker(args.origin, tooltip="Origin", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(args.destination, tooltip="Destination", icon=folium.Icon(color="red")).add_to(m)

    # Corridor subgraph edges: the extent Yen/traffic sampling will operate on.
    # Colour by why a node is in the corridor: inside the ellipse bound, or
    # only pulled in by the buffered union of the k candidate paths.
    corridor_layer = folium.FeatureGroup(name="Corridor subgraph")
    for full_u in result.subgraph.sub_to_full:
        su = int(result.subgraph.full_to_sub[full_u])
        color = "#999999" if result.ellipse_mask[full_u] else "#e6a817"
        for pos in range(result.subgraph.indptr[su], result.subgraph.indptr[su + 1]):
            full_v = int(result.subgraph.sub_to_full[result.subgraph.indices[pos]])
            lon_u, lat_u = to_wgs84.transform(csr.x[full_u], csr.y[full_u])
            lon_v, lat_v = to_wgs84.transform(csr.x[full_v], csr.y[full_v])
            folium.PolyLine(
                [(lat_u, lon_u), (lat_v, lon_v)], color=color, weight=1, opacity=0.6
            ).add_to(corridor_layer)
    corridor_layer.add_to(m)

    # Buffer polygon around the union of Yen's k paths (usually one polygon,
    # since the paths share their origin/destination; guard against the
    # buffer union splitting into disjoint pieces just in case).
    if result.buffer_polygon is not None:
        buffer_layer = folium.FeatureGroup(name="Buffer polygon")
        polygons = getattr(result.buffer_polygon, "geoms", [result.buffer_polygon])
        for polygon in polygons:
            exterior_latlon = [
                to_wgs84.transform(px, py)[::-1] for px, py in polygon.exterior.coords
            ]
            folium.Polygon(
                exterior_latlon, color="#e6a817", weight=1, fill=True, fill_opacity=0.08
            ).add_to(buffer_layer)
        buffer_layer.add_to(m)

    # Yen's k candidate paths, cheapest first.
    paths_layer = folium.FeatureGroup(name="Candidate paths (Yen)")
    for i, path in enumerate(result.candidate_paths):
        latlon = [to_wgs84.transform(csr.x[n], csr.y[n])[::-1] for n in path]
        folium.PolyLine(
            latlon,
            color=PATH_COLORS[i % len(PATH_COLORS)],
            weight=4 if i == 0 else 2,
            opacity=0.9,
            tooltip=f"Path {i}: {result.candidate_costs[i]:.1f}s",
        ).add_to(paths_layer)
    paths_layer.add_to(m)

    folium.LayerControl().add_to(m)
    m.save(args.out)
    print(f"Saved map to {args.out}")


if __name__ == "__main__":
    main()
