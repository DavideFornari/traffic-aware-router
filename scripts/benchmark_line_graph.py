"""Benchmark: line graph size and Dijkstra/A* timing vs the plain node graph.

Downloads (and caches) the full default area, builds both the node-graph
CSR and the line-graph CSR, fetches real turn restrictions from Overpass by
default, and times several random origin/destination queries on each.
CLAUDE.md expects roughly 3-4x the node count for the line graph; this is
the reproducible way to measure the actual ratio (and its timing cost) and
regenerate the numbers quoted in the README.

Usage: python scripts/benchmark_line_graph.py [--no-restrictions]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from router.core.astar import astar
from router.core.dijkstra import dijkstra
from router.graph.config import verona
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.line_graph import build_line_graph
from router.graph.prepare import max_speed_kph, prepare_graph
from router.graph.restrictions import fetch_turn_restrictions, graph_bbox, resolve_restrictions

N_QUERIES = 20
SEED = 42


def _time_it(fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _random_pairs(rng: random.Random, n: int, count: int) -> list[tuple[int, int]]:
    indices = list(range(n))
    pairs = [(rng.choice(indices), rng.choice(indices)) for _ in range(count)]
    return [(s, t) for s, t in pairs if s != t]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-restrictions",
        action="store_true",
        help="skip fetching real restrictions from Overpass (faster, but less realistic)",
    )
    args = parser.parse_args()

    print("Loading and preparing graph...")
    raw = load_graph(verona())
    graph = prepare_graph(raw)

    restrictions = []
    if not args.no_restrictions:
        print("Fetching turn restrictions from Overpass...")
        south, west, north, east = graph_bbox(raw)
        raw_restrictions = fetch_turn_restrictions(south, west, north, east)
        restrictions = resolve_restrictions(graph, raw_restrictions)
        print(
            f"Fetched {len(raw_restrictions)} restriction relations, "
            f"resolved {len(restrictions)} to graph edges."
        )

    node_csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600

    line_graph = build_line_graph(graph, restrictions=restrictions)
    line_csr = build_csr(line_graph, weight="weight")

    print(f"\nNode graph:  {node_csr.n_nodes} nodes, {node_csr.n_edges} edges")
    print(f"Line graph:  {line_csr.n_nodes} nodes, {line_csr.n_edges} edges")
    print(f"Node-count ratio: {line_csr.n_nodes / node_csr.n_nodes:.2f}x")

    # Node-graph and line-graph queries use independently sampled random
    # pairs on each graph — this measures typical query cost on each
    # representation, not the cost of the same physical route on both.
    rng = random.Random(SEED)
    node_pairs = _random_pairs(rng, node_csr.n_nodes, N_QUERIES)
    line_pairs = _random_pairs(rng, line_csr.n_nodes, N_QUERIES)

    node_dij_times = [
        _time_it(
            lambda s=s, t=t: dijkstra(node_csr.indptr, node_csr.indices, node_csr.weights, s, t)
        )
        for s, t in node_pairs
    ]
    line_dij_times = [
        _time_it(
            lambda s=s, t=t: dijkstra(line_csr.indptr, line_csr.indices, line_csr.weights, s, t)
        )
        for s, t in line_pairs
    ]
    line_astar_times = [
        _time_it(
            lambda s=s, t=t: astar(
                line_csr.indptr,
                line_csr.indices,
                line_csr.weights,
                line_csr.lat,
                line_csr.lon,
                v_max_mps,
                s,
                t,
            )
        )
        for s, t in line_pairs
    ]

    print(f"\nQueries: {len(node_pairs)} node-graph, {len(line_pairs)} line-graph\n")
    print("| Graph | Algorithm | Mean wall time (ms) |")
    print("|---|---|---|")
    print(f"| Node graph | Dijkstra | {1000 * sum(node_dij_times) / len(node_dij_times):.3f} |")
    print(f"| Line graph | Dijkstra | {1000 * sum(line_dij_times) / len(line_dij_times):.3f} |")
    print(f"| Line graph | A* | {1000 * sum(line_astar_times) / len(line_astar_times):.3f} |")


if __name__ == "__main__":
    main()
