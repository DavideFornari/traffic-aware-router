"""Streamlit UI: pick origin/destination, compare free-flow vs traffic-aware routes.

Run with `streamlit run app/main.py`. Works with no TomTom API key at all —
falls back to free-flow-only routing and says so (see `helpers.traffic_summary`),
per CLAUDE.md's hard constraint that the app must not depend on someone
else's credentials to start.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import folium
import osmnx as ox
import streamlit as st
from pyproj import Transformer
from streamlit_folium import st_folium

from app.helpers import (
    format_delta,
    format_duration,
    nearest_node,
    parse_latlon,
    path_to_latlon,
    source_node_of_position,
    traffic_summary,
)
from router.core.dijkstra import dijkstra, reconstruct_path
from router.corridor.pipeline import build_corridor
from router.graph.config import AreaConfig
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.prepare import max_speed_kph, prepare_graph
from router.traffic.cache import TrafficCache
from router.traffic.client import TomTomClient
from router.traffic.pipeline import apply_traffic

st.set_page_config(page_title="Traffic-aware router", layout="wide")

DEFAULT_ORIGIN = (45.4384, 10.9916)  # Piazza Bra
DEFAULT_DESTINATION = (45.4353, 10.9548)  # Stadio Bentegodi


@st.cache_resource(show_spinner="Downloading and preparing the road network…")
def load_area(place: str):
    raw = load_graph(AreaConfig(place=place))
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600
    to_wgs84 = Transformer.from_crs(graph.graph["crs"], "EPSG:4326", always_xy=True)
    to_projected = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True)
    return csr, v_max_mps, to_wgs84, to_projected


def geocode(query: str) -> tuple[float, float] | None:
    try:
        lat, lon = ox.geocode(query)
        return (lat, lon)
    except Exception:
        return None


def render_result() -> None:
    """Render the last computed route comparison, if any.

    Called on every rerun (not just right after "Compute route" is clicked),
    reading only `st.session_state.result` — plain lat/lon data, not `csr`/
    `corridor` objects — so a map click or widget tweak afterwards doesn't
    erase the comparison the way gating everything behind the button did.
    """
    result = st.session_state.get("result")
    if result is None:
        return

    st.subheader("Comparison")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Free-flow ETA", format_duration(result["free_flow_eta"]))
    metric_cols[1].metric("Traffic-aware ETA", format_duration(result["traffic_eta"]))
    metric_cols[2].metric("Delta", format_delta(result["traffic_eta"] - result["free_flow_eta"]))

    if not result["traffic_key_available"]:
        st.warning(result["traffic_status"])
    else:
        st.info(result["traffic_status"])

    result_map = folium.Map(location=list(result["origin_latlon"]), zoom_start=13)
    folium.Marker(
        result["origin_latlon"], tooltip="Origin", icon=folium.Icon(color="green")
    ).add_to(result_map)
    folium.Marker(
        result["destination_latlon"], tooltip="Destination", icon=folium.Icon(color="red")
    ).add_to(result_map)

    corridor_layer = folium.FeatureGroup(name="Corridor")
    for start, end in result["corridor_edges_latlon"]:
        folium.PolyLine([start, end], color="#999999", weight=1, opacity=0.4).add_to(corridor_layer)
    corridor_layer.add_to(result_map)

    if result["live_edges_latlon"]:
        live_layer = folium.FeatureGroup(name="Live traffic data")
        for start, end in result["live_edges_latlon"]:
            folium.PolyLine([start, end], color="#e6a817", weight=4, opacity=0.8).add_to(live_layer)
        live_layer.add_to(result_map)

    folium.PolyLine(
        result["free_flow_latlon"], color="#1f77b4", weight=5, tooltip="Free-flow route"
    ).add_to(result_map)
    folium.PolyLine(
        result["traffic_latlon"],
        color="#d62728",
        weight=3,
        dash_array="6",
        tooltip="Traffic-aware route",
    ).add_to(result_map)

    folium.LayerControl().add_to(result_map)
    st_folium(result_map, height=500, width=None, returned_objects=[])


def main() -> None:
    st.title("Traffic-aware router")
    st.caption(
        "Static free-flow shortest path (Dijkstra on the full network) vs a traffic-adjusted "
        "second pass on a bounded corridor. See README.md for the modelling assumptions."
    )

    if "origin" not in st.session_state:
        st.session_state.origin = DEFAULT_ORIGIN
    if "destination" not in st.session_state:
        st.session_state.destination = DEFAULT_DESTINATION
    if "traffic_cache" not in st.session_state:
        st.session_state.traffic_cache = TrafficCache()

    with st.sidebar:
        st.header("Area")
        place = st.text_input("OSM place name", value="Verona, Italy")

        st.header("Corridor parameters")
        epsilon = st.slider("Ellipse epsilon", 0.0, 1.0, 0.3, 0.05)
        k = st.slider("Yen's k candidate paths", 1, 8, 4)

        st.header("Traffic")
        api_key = st.text_input("TomTom API key (optional)", type="password")
        st.caption("Get a free key at developer.tomtom.com — no credit card required.")

        st.header("Origin / destination")
        pick_mode = st.radio("Clicking the map sets", ["Origin", "Destination"], horizontal=True)
        st.caption(f"Origin: {st.session_state.origin[0]:.5f}, {st.session_state.origin[1]:.5f}")
        st.caption(
            f"Destination: {st.session_state.destination[0]:.5f}, "
            f"{st.session_state.destination[1]:.5f}"
        )

        search_col1, search_col2 = st.columns(2)
        origin_query = search_col1.text_input("Search origin", key="origin_query")
        destination_query = search_col2.text_input("Search destination", key="destination_query")
        if st.button("Search"):
            if origin_query:
                found = geocode(origin_query)
                if found:
                    st.session_state.origin = found
                else:
                    st.warning(f"Couldn't find {origin_query!r}.")
            if destination_query:
                found = geocode(destination_query)
                if found:
                    st.session_state.destination = found
                else:
                    st.warning(f"Couldn't find {destination_query!r}.")

    csr, v_max_mps, to_wgs84_t, to_projected_t = load_area(place)
    st.caption(f"Loaded {csr.n_nodes:,} nodes, {csr.n_edges:,} edges.")

    picker_map = folium.Map(location=list(st.session_state.origin), zoom_start=13)
    folium.Marker(
        st.session_state.origin, tooltip="Origin", icon=folium.Icon(color="green")
    ).add_to(picker_map)
    folium.Marker(
        st.session_state.destination, tooltip="Destination", icon=folium.Icon(color="red")
    ).add_to(picker_map)
    click = st_folium(picker_map, height=400, width=None, returned_objects=["last_clicked"])

    if click and click.get("last_clicked"):
        clicked = (click["last_clicked"]["lat"], click["last_clicked"]["lng"])
        if pick_mode == "Origin":
            st.session_state.origin = clicked
        else:
            st.session_state.destination = clicked

    manual_col1, manual_col2 = st.columns(2)
    origin_text = manual_col1.text_input(
        "Origin (lat, lon)", value=f"{st.session_state.origin[0]}, {st.session_state.origin[1]}"
    )
    destination_text = manual_col2.text_input(
        "Destination (lat, lon)",
        value=f"{st.session_state.destination[0]}, {st.session_state.destination[1]}",
    )
    parsed_origin = parse_latlon(origin_text)
    parsed_destination = parse_latlon(destination_text)
    if parsed_origin:
        st.session_state.origin = parsed_origin
    if parsed_destination:
        st.session_state.destination = parsed_destination

    if st.button("Compute route", type="primary"):
        origin = nearest_node(csr.lat, csr.lon, st.session_state.origin)
        destination = nearest_node(csr.lat, csr.lon, st.session_state.destination)
        if origin == destination:
            st.error("Origin and destination snapped to the same graph node — pick farther apart.")
        else:
            free_flow = dijkstra(csr.indptr, csr.indices, csr.weights, origin, destination)
            if math.isinf(free_flow.dist[destination]):
                st.error("No route exists between origin and destination on this network.")
            else:
                free_flow_path = reconstruct_path(free_flow.predecessor, origin, destination)

                corridor = build_corridor(
                    csr.indptr,
                    csr.indices,
                    csr.weights,
                    csr.x,
                    csr.y,
                    origin,
                    destination,
                    v_max_mps,
                    epsilon=epsilon,
                    k=k,
                )

                client = TomTomClient(api_key=api_key or None)
                sub_x = csr.x[corridor.subgraph.sub_to_full]
                sub_y = csr.y[corridor.subgraph.sub_to_full]
                sub_origin = int(corridor.subgraph.full_to_sub[origin])
                sub_destination = int(corridor.subgraph.full_to_sub[destination])

                traffic = apply_traffic(
                    corridor.subgraph.indptr,
                    corridor.subgraph.indices,
                    corridor.subgraph.weights,
                    sub_x,
                    sub_y,
                    lambda x, y: to_wgs84_t.transform(x, y)[::-1],
                    lambda lat, lon: to_projected_t.transform(lon, lat),
                    client,
                    cache=st.session_state.traffic_cache,
                )
                traffic_result = dijkstra(
                    corridor.subgraph.indptr,
                    corridor.subgraph.indices,
                    traffic.adjusted_weights,
                    sub_origin,
                    sub_destination,
                )
                traffic_path_sub = reconstruct_path(
                    traffic_result.predecessor, sub_origin, sub_destination
                )
                traffic_path_full = [
                    int(corridor.subgraph.sub_to_full[i]) for i in traffic_path_sub
                ]

                # Resolve everything to lat/lon (and plain values) now, at compute
                # time: the rendering below must survive later Streamlit reruns
                # (e.g. a map click) without depending on `csr`/`corridor`, which
                # would silently misindex if the area or corridor params change
                # before the next "Compute route" click.
                corridor_edges_latlon = []
                for su in range(corridor.subgraph.n_nodes):
                    full_u = int(corridor.subgraph.sub_to_full[su])
                    for pos in range(
                        corridor.subgraph.indptr[su], corridor.subgraph.indptr[su + 1]
                    ):
                        full_v = int(corridor.subgraph.sub_to_full[corridor.subgraph.indices[pos]])
                        corridor_edges_latlon.append(
                            (
                                (float(csr.lat[full_u]), float(csr.lon[full_u])),
                                (float(csr.lat[full_v]), float(csr.lon[full_v])),
                            )
                        )

                live_edges_latlon = []
                for pos in traffic.matched_edge_positions:
                    su = source_node_of_position(corridor.subgraph.indptr, pos)
                    sv = int(corridor.subgraph.indices[pos])
                    full_u = int(corridor.subgraph.sub_to_full[su])
                    full_v = int(corridor.subgraph.sub_to_full[sv])
                    live_edges_latlon.append(
                        (
                            (float(csr.lat[full_u]), float(csr.lon[full_u])),
                            (float(csr.lat[full_v]), float(csr.lon[full_v])),
                        )
                    )

                st.session_state.result = {
                    "origin_latlon": st.session_state.origin,
                    "destination_latlon": st.session_state.destination,
                    "free_flow_eta": float(free_flow.dist[destination]),
                    "traffic_eta": float(traffic_result.dist[sub_destination]),
                    "free_flow_latlon": path_to_latlon(free_flow_path, csr.lat, csr.lon),
                    "traffic_latlon": path_to_latlon(traffic_path_full, csr.lat, csr.lon),
                    "corridor_edges_latlon": corridor_edges_latlon,
                    "live_edges_latlon": live_edges_latlon,
                    "traffic_status": traffic_summary(traffic),
                    "traffic_key_available": client.is_available,
                }

    render_result()


if __name__ == "__main__":
    main()
