"""Generate the route-comparison image at the top of the README.

No live TomTom key is used here: instead of the real traffic pipeline,
this script *synthetically* congests the free-flow route's own edges
within the corridor (multiplies their travel time) and re-runs Dijkstra,
so the two routes genuinely diverge for an illustrative comparison. This
is clearly not live traffic data, and the image says so.

Usage: python scripts/generate_screenshot.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import osmnx as ox
from app.helpers import nearest_node

from router.core.dijkstra import dijkstra, reconstruct_path
from router.corridor.pipeline import build_corridor
from router.graph.config import verona
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.prepare import max_speed_kph, prepare_graph

ORIGIN = (45.4384, 10.9916)  # Piazza Bra
DESTINATION = (45.4353, 10.9548)  # Stadio Bentegodi
CONGESTION_FACTOR = 4.0
OUT_PATH = Path(__file__).parent.parent / "docs" / "route_comparison.png"


def main() -> None:
    print("Loading and preparing graph...")
    raw = load_graph(verona())
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600

    origin = nearest_node(csr.lat, csr.lon, ORIGIN)
    destination = nearest_node(csr.lat, csr.lon, DESTINATION)

    free_flow = dijkstra(csr.indptr, csr.indices, csr.weights, origin, destination)
    free_flow_path = reconstruct_path(free_flow.predecessor, origin, destination)

    corridor = build_corridor(
        csr.indptr, csr.indices, csr.weights, csr.x, csr.y, origin, destination, v_max_mps
    )

    # Synthetically congest the free-flow route's own edges within the
    # corridor, then re-run Dijkstra there: this stands in for a real
    # traffic-adjusted second pass without needing a live TomTom key.
    congested_weights = corridor.subgraph.weights.copy()
    sub_path = [int(corridor.subgraph.full_to_sub[n]) for n in free_flow_path]
    for u, v in itertools.pairwise(sub_path):
        for pos in range(corridor.subgraph.indptr[u], corridor.subgraph.indptr[u + 1]):
            if corridor.subgraph.indices[pos] == v:
                congested_weights[pos] *= CONGESTION_FACTOR

    sub_origin = int(corridor.subgraph.full_to_sub[origin])
    sub_destination = int(corridor.subgraph.full_to_sub[destination])
    congested = dijkstra(
        corridor.subgraph.indptr,
        corridor.subgraph.indices,
        congested_weights,
        sub_origin,
        sub_destination,
    )
    congested_sub_path = reconstruct_path(congested.predecessor, sub_origin, sub_destination)
    congested_path = [int(corridor.subgraph.sub_to_full[n]) for n in congested_sub_path]

    free_flow_osmids = [int(csr.node_ids[n]) for n in free_flow_path]
    congested_osmids = [int(csr.node_ids[n]) for n in congested_path]

    corridor_osmids = [int(csr.node_ids[n]) for n in corridor.subgraph.sub_to_full]
    corridor_graph = graph.subgraph(corridor_osmids)

    # Crop to the two routes' own extent (plus a margin), not the whole
    # corridor: the corridor can legitimately span much more of the city
    # than the routes themselves (see the corridor benchmark in the README).
    route_nodes = set(free_flow_path) | set(congested_path)
    margin_m = 400.0
    x_min = min(csr.x[n] for n in route_nodes) - margin_m
    x_max = max(csr.x[n] for n in route_nodes) + margin_m
    y_min = min(csr.y[n] for n in route_nodes) - margin_m
    y_max = max(csr.y[n] for n in route_nodes) + margin_m

    print(
        f"Free-flow: {free_flow.dist[destination]:.0f}s, "
        f"congested: {congested.dist[sub_destination]:.0f}s"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = ox.plot_graph_routes(
        corridor_graph,
        routes=[free_flow_osmids, congested_osmids],
        route_colors=["#1f77b4", "#d62728"],
        route_linewidths=[5, 3],
        node_size=0,
        bgcolor="white",
        edge_color="#cccccc",
        show=False,
        close=False,
        save=False,
    )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_title(
        "Blue: free-flow route   Red: reroute under simulated congestion on the blue route\n"
        "(synthetic — not live TomTom data)",
        fontsize=10,
    )
    fig.savefig(OUT_PATH, dpi=200, bbox_inches="tight")
    print(f"Saved {OUT_PATH}")


if __name__ == "__main__":
    main()
