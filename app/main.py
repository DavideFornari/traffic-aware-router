"""Streamlit UI: pick origin/destination, compare free-flow vs traffic-aware routes.

Run with `streamlit run app/main.py`. Works with no TomTom API key at all —
falls back to free-flow-only routing and says so (see `helpers.traffic_summary`),
per CLAUDE.md's hard constraint that the app must not depend on someone
else's credentials to start.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import folium
import numpy as np
import osmnx as ox
import streamlit as st
from dotenv import load_dotenv
from pyproj import Transformer
from streamlit_folium import st_folium

from app.helpers import (
    apply_map_click,
    format_delta,
    format_duration,
    nearest_edge_endpoints,
    parse_latlon,
    path_to_latlon,
    select_best_endpoints,
    source_node_of_position,
    traffic_summary,
)
from router.core.dijkstra import dijkstra, reconstruct_path
from router.corridor.pipeline import build_corridor
from router.corridor.restricted_second_pass import route_corridor_second_pass
from router.graph.config import AreaConfig
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.prepare import max_speed_kph, prepare_graph
from router.graph.restrictions import fetch_turn_restrictions, graph_bbox, resolve_restrictions
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

    # Fetched once per area (cached alongside the graph, not per query): turn
    # restrictions apply to the traffic-aware second pass regardless of which
    # origin/destination is queried against this area (CLAUDE.md P1 #1).
    south, west, north, east = graph_bbox(raw)
    try:
        raw_restrictions = fetch_turn_restrictions(south, west, north, east)
        restrictions = resolve_restrictions(graph, raw_restrictions)
    except Exception:
        # Overpass can time out or be unreachable; routing must still work
        # with no turn restrictions applied, same spirit as the no-TomTom-key
        # fallback — a missing external service degrades, never blocks.
        restrictions = []

    return csr, graph, v_max_mps, to_wgs84, to_projected, restrictions


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

    if result["approach_total"] > 5.0:
        st.caption(
            f"Includes ~{format_duration(result['approach_total'])} to reach the road network "
            "from the exact origin/destination points — they can land mid-way along a long "
            "merged OSM edge (e.g. a street that continues across a bridge under a different "
            "name), not right at a routable intersection. See README's UI section."
        )

    if result["restriction_count"]:
        if result["restrictions_applied"]:
            st.caption(
                f"Traffic-aware route respects {result['restriction_count']:,} known turn "
                "restrictions in this area; the free-flow route above does not (it stays on "
                "the plain road network to keep the first pass cheap — see README)."
            )
        else:
            st.caption(
                "Every route within the corridor was blocked by a turn restriction, so this "
                "traffic-aware route ignores them too rather than failing outright."
            )

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

    # Approach segments: pin -> nearest routable node, following the snapped
    # edge's own geometry. Deliberately styled distinctly from the routed
    # lines below (thin, dotted, grey) — this portion is an interpolated
    # estimate, not something the corridor/traffic pipeline actually routed.
    for connector in (result["origin_connector_latlon"], result["destination_connector_latlon"]):
        folium.PolyLine(
            connector,
            color="#555555",
            weight=2,
            dash_array="2,6",
            opacity=0.7,
            tooltip="Approach to the road network (estimated)",
        ).add_to(result_map)

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
    # Loads TOMTOM_API_KEY (and anything else) from a `.env` file in the
    # project root into the environment, if present — never overrides a
    # variable already set in the real environment. `.env` itself is
    # gitignored; see .env.example.
    load_dotenv()

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
    if "pick_mode" not in st.session_state:
        st.session_state.pick_mode = None  # "Origin", "Destination", or None (inactive)
    if "last_map_click" not in st.session_state:
        st.session_state.last_map_click = None

    with st.sidebar:
        st.header("Area")
        place = st.text_input("OSM place name", value="Verona, Italy")

        st.header("Corridor parameters")
        epsilon = st.slider("Ellipse epsilon", 0.0, 1.0, 0.3, 0.05)
        k = st.slider("Yen's k candidate paths", 1, 8, 4)

        st.header("Traffic")
        env_key = os.environ.get("TOMTOM_API_KEY")
        use_env_key = st.toggle(
            "Use TOMTOM_API_KEY from environment / .env file",
            value=bool(env_key),
            disabled=not env_key,
        )
        if use_env_key:
            api_key = env_key
            st.caption("✓ Using the key from the environment." if env_key else "")
        else:
            api_key = st.text_input("TomTom API key (optional)", type="password")
        if not env_key:
            st.caption(
                "No TOMTOM_API_KEY found in the environment or a `.env` file — copy "
                "`.env.example` to `.env` and fill it in to avoid pasting a key here "
                "every session."
            )
        st.caption("Get a free key at developer.tomtom.com — no credit card required.")

        st.header("Origin / destination")
        st.caption("Pick a point below, then click the map once — it deactivates after use.")
        pick_col1, pick_col2 = st.columns(2)
        origin_picking = st.session_state.pick_mode == "Origin"
        destination_picking = st.session_state.pick_mode == "Destination"
        if pick_col1.button(
            "📍 Pick origin…" if not origin_picking else "Click the map…",
            type="primary" if origin_picking else "secondary",
            use_container_width=True,
        ):
            st.session_state.pick_mode = None if origin_picking else "Origin"
            st.rerun()  # otherwise this button's own new label lags by one rerun
        if pick_col2.button(
            "📍 Pick destination…" if not destination_picking else "Click the map…",
            type="primary" if destination_picking else "secondary",
            use_container_width=True,
        ):
            st.session_state.pick_mode = None if destination_picking else "Destination"
            st.rerun()

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

    csr, graph, v_max_mps, to_wgs84_t, to_projected_t, restrictions = load_area(place)
    st.caption(
        f"Loaded {csr.n_nodes:,} nodes, {csr.n_edges:,} edges, "
        f"{len(restrictions):,} turn restrictions."
    )

    if st.session_state.pick_mode:
        st.info(f"Click the map to set the {st.session_state.pick_mode.lower()}.")

    picker_map = folium.Map(location=list(st.session_state.origin), zoom_start=13)
    folium.Marker(
        st.session_state.origin, tooltip="Origin", icon=folium.Icon(color="green")
    ).add_to(picker_map)
    folium.Marker(
        st.session_state.destination, tooltip="Destination", icon=folium.Icon(color="red")
    ).add_to(picker_map)
    click = st_folium(picker_map, height=400, width=None, returned_objects=["last_clicked"])

    clicked = None
    if click and click.get("last_clicked"):
        clicked = (click["last_clicked"]["lat"], click["last_clicked"]["lng"])

    prior_pick_mode = st.session_state.pick_mode
    click_result = apply_map_click(
        clicked,
        st.session_state.last_map_click,
        st.session_state.pick_mode,
        st.session_state.origin,
        st.session_state.destination,
    )
    picked_something = prior_pick_mode is not None and click_result.pick_mode is None
    st.session_state.origin = click_result.origin
    st.session_state.destination = click_result.destination
    st.session_state.last_map_click = click_result.last_map_click
    st.session_state.pick_mode = click_result.pick_mode
    if picked_something:
        # The marker and picker-map center were already drawn above from the
        # *old* origin/destination this run — without an immediate rerun the
        # pick only becomes visible after some later, unrelated interaction
        # forces the next one (same lag the pick buttons' own labels had).
        st.rerun()

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
        # Snap to the nearest *edge*, not the nearest node/intersection: a
        # typed address or a click usually lands mid-block, and the nearest
        # intersection to that point is often not the intersection you'd
        # actually leave from. Both of that edge's endpoints are candidate
        # start/end nodes; select_best_endpoints picks whichever pair gives
        # the cheaper route rather than assuming the geometrically closer
        # endpoint is the routing-wise better one (see app/helpers.py).
        origin_x, origin_y = to_projected_t.transform(
            st.session_state.origin[1], st.session_state.origin[0]
        )
        destination_x, destination_y = to_projected_t.transform(
            st.session_state.destination[1], st.session_state.destination[0]
        )
        origin_snap = nearest_edge_endpoints(graph, origin_x, origin_y)
        destination_snap = nearest_edge_endpoints(graph, destination_x, destination_y)
        origin_candidates = tuple(
            (int(np.searchsorted(csr.node_ids, n)), approach)
            for n, approach in origin_snap.candidates
        )
        destination_candidates = tuple(
            (int(np.searchsorted(csr.node_ids, n)), approach)
            for n, approach in destination_snap.candidates
        )
        origin, destination = select_best_endpoints(
            csr.indptr, csr.indices, csr.weights, origin_candidates, destination_candidates
        )
        # The approach cost of whichever candidate was actually chosen —
        # added to the reported ETA below, so it stays consistent with what
        # select_best_endpoints just used to make that choice, rather than
        # silently dropping it from the displayed number.
        origin_approach = dict(origin_candidates)[origin]
        destination_approach = dict(destination_candidates)[destination]
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
                    edge_keys=csr.edge_keys,
                )

                client = TomTomClient(api_key=api_key or None)
                sub_x = csr.x[corridor.subgraph.sub_to_full]
                sub_y = csr.y[corridor.subgraph.sub_to_full]

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

                # Second pass: route on the corridor's line graph, so turn
                # restrictions and turn penalties are respected (CLAUDE.md P1
                # #1) — unlike the free-flow first pass above, which stays on
                # the plain node graph since it only needs to cheaply bound
                # the corridor, not be the final answer (see
                # restricted_second_pass.py's module docstring).
                origin_real_id = int(csr.node_ids[origin])
                destination_real_id = int(csr.node_ids[destination])

                # The approach segment: the query point is often not right at
                # a routable node (see nearest_edge_endpoints), so without
                # this the drawn route would visually start/end at the
                # chosen node instead of the actual pin, disagreeing with
                # what's on the map. Follows the snapped edge's own geometry
                # (not a straight line) so a long merged edge — e.g. one that
                # crosses a bridge — is drawn crossing the bridge, not
                # cutting across whatever it goes around.
                origin_connector_latlon = [st.session_state.origin] + [
                    to_wgs84_t.transform(x, y)[::-1]
                    for x, y in origin_snap.connector_coords(origin_real_id)
                ]
                destination_connector_latlon = [
                    to_wgs84_t.transform(x, y)[::-1]
                    for x, y in reversed(destination_snap.connector_coords(destination_real_id))
                ] + [st.session_state.destination]

                second_pass = route_corridor_second_pass(
                    corridor.subgraph,
                    csr.node_ids[corridor.subgraph.sub_to_full],
                    csr.lat[corridor.subgraph.sub_to_full],
                    csr.lon[corridor.subgraph.sub_to_full],
                    sub_x,
                    sub_y,
                    traffic.adjusted_weights,
                    origin_real_id,
                    destination_real_id,
                    restrictions=restrictions,
                )
                restrictions_applied = second_pass is not None
                if second_pass is None:
                    # Every route within the corridor is blocked by a turn
                    # restriction (rare, but possible with a tight corridor) —
                    # fall back to the unrestricted route rather than a dead
                    # end, same resilience principle as the no-TomTom-key path.
                    second_pass = route_corridor_second_pass(
                        corridor.subgraph,
                        csr.node_ids[corridor.subgraph.sub_to_full],
                        csr.lat[corridor.subgraph.sub_to_full],
                        csr.lon[corridor.subgraph.sub_to_full],
                        sub_x,
                        sub_y,
                        traffic.adjusted_weights,
                        origin_real_id,
                        destination_real_id,
                        restrictions=None,
                    )

                if second_pass is None:
                    # Shouldn't happen — the corridor always contains the
                    # free-flow route already confirmed reachable above — but
                    # never crash on a routing edge case; report it instead.
                    st.error("Could not compute a traffic-aware route within the corridor.")
                    st.stop()

                traffic_real_path, traffic_eta = second_pass
                traffic_path_full = [
                    int(np.searchsorted(csr.node_ids, real_id)) for real_id in traffic_real_path
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

                approach_total = origin_approach + destination_approach
                st.session_state.result = {
                    "origin_latlon": st.session_state.origin,
                    "destination_latlon": st.session_state.destination,
                    "free_flow_eta": float(free_flow.dist[destination]) + approach_total,
                    "traffic_eta": float(traffic_eta) + approach_total,
                    "free_flow_latlon": path_to_latlon(free_flow_path, csr.lat, csr.lon),
                    "traffic_latlon": path_to_latlon(traffic_path_full, csr.lat, csr.lon),
                    "corridor_edges_latlon": corridor_edges_latlon,
                    "live_edges_latlon": live_edges_latlon,
                    "traffic_status": traffic_summary(traffic),
                    "traffic_key_available": client.is_available,
                    "restrictions_applied": restrictions_applied,
                    "restriction_count": len(restrictions),
                    "approach_total": approach_total,
                    "origin_connector_latlon": origin_connector_latlon,
                    "destination_connector_latlon": destination_connector_latlon,
                }

    render_result()


if __name__ == "__main__":
    main()
