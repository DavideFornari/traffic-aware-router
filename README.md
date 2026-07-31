# Traffic-aware router

A router that computes the best path between two points on a real road network, weighting edges
by both free-flow travel time and live traffic. Default area is Verona, Italy, but the area is
configuration — any OpenStreetMap place name or bounding box works.

This is a portfolio project focused on **modelling and algorithms**, not data plumbing: Dijkstra,
A*, and Yen's k-shortest-paths are implemented from scratch over a compact array-based graph
representation, with `networkx` used only as a correctness oracle in tests.

## Status

**Milestone 3 — routing core.** Dijkstra and A* are implemented from scratch over CSR arrays,
verified against networkx (property-based tests with `hypothesis`, plus golden tests on the
committed Verona extract) and benchmarked on the full Verona network. See the roadmap below.

## Modelling assumptions

- **Static snapshot model.** Traffic is sampled once, when the route is requested, and edge
  weights are fixed during the search. This is not time-dependent routing.
- **Free-flow time, not length, is the base metric.** Minimising metres returns implausible
  back-street routes and excludes fast roads from the search corridor.
- All geometric reasoning (ellipse, buffers, matching) happens after projecting to a local metric
  CRS (UTM zone of the area), never in raw lat/lon degrees.

Full design rationale — the two-pass corridor/traffic pipeline, the ellipse containment bound,
turn-restriction handling via the line graph — is in `CLAUDE.md` and will be promoted into this
README as each part is implemented.

## Architecture

The routing core is graph-agnostic: it never sees OSM, networkx, or TomTom directly. Adapters
convert OSM graphs (and, later, a line graph for turn restrictions) into CSR-style arrays that
the core algorithms operate on.

```
src/router/core/       routing algorithms (Dijkstra, A*, Yen) over CSR arrays
src/router/graph/      OSM download, caching, adapters, line graph
src/router/traffic/    TomTom client, matching, cache
src/router/corridor/   ellipse bound, k-paths, subgraph extraction
app/                   Streamlit UI
```

`src/router/graph/` currently provides:

- `AreaConfig` / `verona()` — the area to route on (OSM place name or bbox), never hardcoded
  past this config object.
- `load_graph` — downloads via osmnx and caches the raw extract to disk as GraphML, keyed by a
  hash of the area config, so repeat runs are instant and offline.
- `prepare_graph` — projects to the area's UTM zone and imputes free-flow speeds/travel times via
  `osmnx.add_edge_speeds` / `add_edge_travel_times`. Missing `maxspeed` is filled with the mean
  speed per highway type, which is optimistic for residential streets.
- `build_csr` — converts any weighted `networkx.MultiDiGraph` (OSM-derived or hand-built) into
  the CSR arrays (`indptr`, `indices`, `weights`) the routing core will operate on; parallel
  edges collapse to their minimum-weight edge.

A small extract around Piazza Bra, Verona (`tests/fixtures/verona_center.graphml`, 66 nodes, 126
edges, © OpenStreetMap contributors, ODbL) is committed as a test fixture and exercised
end-to-end by the golden tests.

`src/router/core/` provides:

- `dijkstra` — single-source shortest path over CSR arrays with a binary heap. Assumes
  non-negative edge weights (stated in the docstring, since that assumption is exactly what
  makes lazy-deletion Dijkstra correct instead of requiring Bellman-Ford).
- `astar` — same search, guided by `heuristic(u) = great_circle_distance(u, target) / v_max`.
  Admissible because no travel-time path can beat covering the remaining straight-line distance
  at the fastest speed anywhere in the graph, so the heuristic never overestimates true remaining
  cost.
- `reconstruct_path` — turns a predecessor array back into a node sequence.

Correctness is checked two ways: `hypothesis`-generated random directed graphs compared against
`networkx.single_source_dijkstra_path_length` (Dijkstra), and against a construction where every
edge weight is `distance / speed` with `speed <= v_max` — which guarantees the A* heuristic is
admissible by the triangle inequality on great-circle distance, so A*'s cost must equal
Dijkstra's (A*); plus golden tests running both algorithms on the committed Verona fixture.

### Benchmark

`scripts/benchmark_core.py` downloads the full default area (not committed; cached under
`data/cache/`) and times 20 random origin/destination queries. On Verona (41,460 nodes, 91,074
edges):

| Algorithm | Mean wall time (ms) | Mean settled nodes |
|---|---|---|
| networkx Dijkstra | 36.5 | n/a |
| Our Dijkstra (CSR) | 13.8 | 17,005 |
| Our A* (CSR) | 15.4 | 9,608 |

Our Dijkstra is ~2.6x faster than networkx's, not the 10–50x CLAUDE.md's architecture notes
anticipate — both implementations are pure Python, so a hand-rolled `heapq` loop saves networkx's
object-graph overhead but doesn't escape Python's per-operation cost. A* settles roughly half the
nodes Dijkstra does (the admissible heuristic prunes the search well) but isn't faster in wall
time here: haversine/trig calls per heap push are expensive enough in pure Python to offset the
work saved. A C-level implementation (numpy-vectorised or `scipy.sparse.csgraph`) would very
likely close both gaps; documented here rather than papered over, since being able to explain a
benchmark's limits is as important to this project as the number itself.

## Development

```bash
make venv    # create .venv and install the project with dev dependencies
make lint    # ruff check + format check
make test    # pytest
make format  # ruff format + autofix
```

The app will run without a TomTom API key: with no key it falls back to free-flow-only routing
and says so in the UI.

## Licences

Code is MIT-licensed (see `LICENSE`). Road network data comes from OpenStreetMap and is
licensed under the Open Database License (ODbL) — © OpenStreetMap contributors,
https://www.openstreetmap.org/copyright. Live traffic data, when available, comes from the
TomTom Traffic API and is subject to TomTom's terms of use.

## Roadmap

1. Scaffolding
2. Graph layer — OSM download, caching, CSR adapter, test fixture
3. Routing core — Dijkstra, A*, hypothesis + golden tests, benchmark *(this milestone)*
4. Corridor — ellipse bound, Yen on the ellipse subgraph
5. Traffic — TomTom client, probe sampling, matching, second pass
6. Turn restrictions — line graph, turn penalties
7. UI — Streamlit map with free-flow vs traffic-aware comparison
8. Documentation and benchmarks
