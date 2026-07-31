"""Benchmark: our Dijkstra/A* (CSR arrays) vs networkx's Dijkstra (object graph).

Downloads (and caches) the full default area, runs several random
origin/destination queries, and reports wall time and settled-node counts.
Not part of the test suite — a reproducible way to regenerate the numbers
quoted in the README.

Usage: python scripts/benchmark_core.py
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import networkx as nx
import numpy as np

from router.core.astar import astar
from router.core.dijkstra import dijkstra
from router.graph.config import verona
from router.graph.csr import build_csr
from router.graph.download import load_graph
from router.graph.prepare import max_speed_kph, prepare_graph

N_QUERIES = 20
SEED = 42


def _time_it(fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def main() -> None:
    print("Loading and preparing graph...")
    raw = load_graph(verona())
    graph = prepare_graph(raw)
    csr = build_csr(graph)
    v_max_mps = max_speed_kph(graph) * 1000 / 3600

    print(f"Nodes: {csr.n_nodes}, edges: {csr.n_edges}")

    rng = random.Random(SEED)
    node_indices = list(range(csr.n_nodes))
    pairs = [(rng.choice(node_indices), rng.choice(node_indices)) for _ in range(N_QUERIES)]
    pairs = [(s, t) for s, t in pairs if s != t]

    nx_times, dij_times, astar_times = [], [], []
    dij_settled, astar_settled = [], []
    mismatches = 0

    for source, target in pairs:
        source_id = int(csr.node_ids[source])
        target_id = int(csr.node_ids[target])

        nx_times.append(
            _time_it(
                lambda s=source_id, t=target_id: nx.shortest_path_length(
                    graph, s, t, weight="travel_time"
                )
            )
        )

        dij_result = None

        def run_dijkstra(s=source, t=target):
            nonlocal dij_result
            dij_result = dijkstra(csr.indptr, csr.indices, csr.weights, source=s, target=t)

        dij_times.append(_time_it(run_dijkstra))
        dij_settled.append(dij_result.settled_count)

        astar_result = None

        def run_astar(s=source, t=target):
            nonlocal astar_result
            astar_result = astar(
                csr.indptr, csr.indices, csr.weights, csr.lat, csr.lon, v_max_mps, s, t
            )

        astar_times.append(_time_it(run_astar))
        astar_settled.append(astar_result.settled_count)

        if not np.isclose(dij_result.dist[target], astar_result.dist[target], rtol=1e-6):
            mismatches += 1

    print(f"\nQueries: {len(pairs)} (mismatched Dijkstra/A* costs: {mismatches})\n")
    print("| Algorithm | Mean wall time (ms) | Mean settled nodes |")
    print("|---|---|---|")
    print(f"| networkx Dijkstra | {1000 * sum(nx_times) / len(nx_times):.3f} | n/a |")
    print(
        f"| Our Dijkstra (CSR) | {1000 * sum(dij_times) / len(dij_times):.3f} "
        f"| {sum(dij_settled) / len(dij_settled):.0f} |"
    )
    print(
        f"| Our A* (CSR) | {1000 * sum(astar_times) / len(astar_times):.3f} "
        f"| {sum(astar_settled) / len(astar_settled):.0f} |"
    )


if __name__ == "__main__":
    main()
