# Traffic-aware router

A router that computes the best path between two points on a real road network, weighting edges
by both free-flow travel time and live traffic. Default area is Verona, Italy, but the area is
configuration — any OpenStreetMap place name or bounding box works.

This is a portfolio project focused on **modelling and algorithms**, not data plumbing: Dijkstra,
A*, and Yen's k-shortest-paths are implemented from scratch over a compact array-based graph
representation, with `networkx` used only as a correctness oracle in tests.

## Status

**Milestone 5 — traffic.** The TomTom Flow Segment Data client, probe sampling, polyline-to-edge
matching (with the bearing check that catches opposite-carriageway mismatches), a TTL cache, and
the traffic-adjusted second pass are in place. The app still runs with no TomTom API key at all —
it falls back to free-flow-only routing. See the roadmap below.

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

`src/router/core/` also provides `yen_k_shortest_paths` — Yen's algorithm for the k shortest
loopless paths, built entirely on `dijkstra`. "Removing" a node or edge for a spur search needs no
change to `dijkstra` itself: it's done by copying the weight array and setting the relevant
entries to infinity, which `dijkstra` already treats as "no edge". Checked against
`networkx.shortest_simple_paths` (matching costs for the k cheapest loopless paths; ties can
break differently between implementations, so costs — not paths — are compared) and against a
golden test on the Verona fixture.

### Corridor (`src/router/corridor/`)

Implements CLAUDE.md's "corridor" step of the two-pass design: a full-graph Dijkstra bounds an
ellipse, Yen then runs only on the (much smaller) ellipse subgraph, and the buffered union of its
k paths is folded back in.

- `ellipse_l_max(t_star, epsilon, v_max)` — the major-axis bound `(1 + epsilon) * t_star *
  v_max`. Any route with free-flow time up to `(1 + epsilon) * t_star` covers at most this many
  metres, since no edge exceeds `v_max` (time bounds distance). Deliberately sized from the
  *time* budget, not `(1 + epsilon)` times the shortest *distance* — a time-optimal route (e.g. a
  ring road) can be far longer in metres than the distance-shortest path, so a distance-based
  bound could wrongly exclude it.
- `in_ellipse` — the focal definition of an ellipse (sum of distances to the two foci at most
  `l_max`) applied directly to projected node coordinates, needing no center, rotation, or
  semi-axis lengths.
- `extract_subgraph` — induced sub-CSR from a boolean node mask, with the index remapping back to
  the full graph, used first to restrict Yen to the ellipse and then to build the final corridor.
- `buffered_path_union` / `nodes_in_polygon` — a `shapely` buffer around the union of Yen's k
  paths, and a vectorised (`shapely.contains_xy`) test for which full-graph nodes it covers —
  this is what recovers a parallel street one block over that the ellipse alone would miss.
- `build_corridor` — wires the above into one call: first-pass Dijkstra for `t_star`, ellipse
  subgraph, Yen on it, buffer union, final corridor subgraph. Also returns the ellipse mask and
  buffer polygon for debugging.

Tested with unit tests on hand-built geometry/graphs for each piece, plus a golden test running
the full pipeline on the Verona fixture. `scripts/debug_corridor.py` (needs the `viz` extra: `pip
install -e ".[viz]"`) renders the corridor on an interactive map — candidate paths, the corridor
subgraph (coloured by whether the ellipse or the buffer pulled a node in), and the buffer polygon
— since this geometry is exactly the kind of thing that's easy to get subtly wrong (wrong CRS, an
inverted containment test) in a way unit tests on synthetic coordinates can miss.

### Traffic (`src/router/traffic/`)

The endpoint, its parameters, and the free tier were checked against TomTom's live docs before
writing any client code, not assumed:

- **Endpoint:** `GET https://api.tomtom.com/traffic/services/4/flowSegmentData/{style}/{zoom}/json
  ?key=...&point={lat},{lon}&unit=kmph`, returning `currentSpeed`, `freeFlowSpeed`,
  `roadClosure`, and the matched segment's own polyline (`coordinates.coordinate[]`).
- **Free tier:** 20,000 requests/month, no credit card required (docs.tomtom.com/pricing,
  checked at implementation time — TomTom can change this, so reverify before relying on it).

Modules:

- `TomTomClient` — wraps the endpoint above. Reads `TOMTOM_API_KEY` from the environment if no
  key is passed explicitly. **With no key, every call is a no-op returning `None`** — this is
  where CLAUDE.md's hard constraint (the app must run without a TomTom key) is actually enforced;
  everything downstream already treats "no traffic data for this edge" as the normal case.
- `sample_probe_points` — places one probe per ~300m of corridor length (default; configurable),
  at edge midpoints, rather than once per OSM edge — a city-scale corridor can have thousands of
  edges, and the free tier is 20,000 requests/month. Deduplicates a two-way street's forward/
  backward edges into a single probe first.
- `edge_matches_segment` — the fiddliest, least visible part of this project (per CLAUDE.md).
  Requires both a buffered geometric overlap *and* a bearing check (reject if the edge's and the
  segment's directions differ by more than ~30 degrees, default). The bearing check specifically
  exists to catch **opposite-carriageway assignment**: a dual carriageway's two directions run a
  few metres apart, so distance alone can't tell them apart, but their directions are ~180
  degrees apart, easily caught by bearing. Documented (but *not* handled — flagged as a real
  limitation) failure mode: **vertically stacked roads** (bridges/underpasses), which look
  identical in this 2D matching regardless of buffer or bearing.
- `TrafficCache` — TTL cache (default 5 minutes) keyed by projected coordinates quantised to a
  ~50m grid, so overlapping corridors or repeat queries reuse probes instead of spending quota.
- `apply_traffic` — the second pass: samples the corridor, fetches/matches each probe, and
  returns a copy of the corridor's weights with matched edges scaled by `free_flow_speed /
  current_speed`. Deliberately resilient at every step — no key, a bad response, a network error,
  an expired key, or a rejected match all just leave that edge at its free-flow weight rather than
  raising, so a route is always produced even when traffic data is partly or wholly unavailable.

Other documented error modes (not specific to the bearing check): a TomTom segment spanning
several short OSM edges, or several TomTom segments covering one long OSM edge — either can leave
a queried edge only partially represented by its match.

Tested with unit tests per module (including the bearing/buffer boundary cases directly), a fully
mocked-HTTP client test suite (no real network calls), and a golden test running the whole second
pass on the Verona fixture's corridor with a fake "always congested" client, asserting the
traffic-aware route is never faster than free-flow.

## Development

```bash
make venv    # create .venv and install the project with dev dependencies
make lint    # ruff check + format check
make test    # pytest
make format  # ruff format + autofix
```

The app will run without a TomTom API key: with no key it falls back to free-flow-only routing
and says so in the UI. To enable live traffic, set `TOMTOM_API_KEY` in your shell environment
(get a free key at developer.tomtom.com — no credit card required). Never commit a real key or a
`.env` file.

## Licences

Code is MIT-licensed (see `LICENSE`). Road network data comes from OpenStreetMap and is
licensed under the Open Database License (ODbL) — © OpenStreetMap contributors,
https://www.openstreetmap.org/copyright. Live traffic data, when available, comes from the
TomTom Traffic API and is subject to TomTom's terms of use.

## Roadmap

1. Scaffolding
2. Graph layer — OSM download, caching, CSR adapter, test fixture
3. Routing core — Dijkstra, A*, hypothesis + golden tests, benchmark
4. Corridor — ellipse bound, Yen on the ellipse subgraph
5. Traffic — TomTom client, probe sampling, matching, second pass *(this milestone)*
6. Turn restrictions — line graph, turn penalties
7. UI — Streamlit map with free-flow vs traffic-aware comparison
8. Documentation and benchmarks
