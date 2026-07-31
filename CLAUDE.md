# Project brief — Traffic-aware router

## Context

I'm a data engineer with a mathematics background, building a portfolio project to demonstrate
algorithmic and modelling skills for job applications. The repository will be public on GitHub
and read by recruiters and technical interviewers, so code quality, documentation and repo
hygiene matter as much as functionality.

This is my second portfolio project. The first (`padova-transit-punctuality`) showed data
engineering. This one is deliberately different: the value is in the **modelling and the
algorithms**, not in the plumbing.

## What we're building

A router that computes the best path between two points on a real road network, weighting edges
by both distance and live traffic.

Default area: **Verona, Italy**. The code must not hardcode it — the area is configuration, and
any OpenStreetMap place name or bounding box should work.

## Modelling assumptions (state these in the README)

- **Static snapshot model.** Traffic is sampled once, when the route is requested, and edge
  weights are fixed during the search. This is *not* time-dependent routing: we do not model the
  traffic an edge will have when the vehicle actually reaches it. Time-dependent weights (and the
  FIFO property they require for Dijkstra to stay correct) are a documented future extension, not
  part of this scope.
- **Free-flow time, not length, is the base metric.** Minimising metres returns implausible
  back-street routes and — worse — excludes fast roads from the corridor, where no amount of
  traffic data can bring them back.
- All geometric reasoning (ellipse, buffers, matching) happens **after projecting to a local
  metric CRS** (UTM zone of the area, via `osmnx.projection`). Never do geometry in raw lat/lon
  degrees.

## Architecture

### Layered design — the routing core is graph-agnostic

The single most important structural rule: **the routing algorithms never see OSM, networkx, or
TomTom.** They operate on a compact array-based graph representation (CSR-style adjacency:
integer node ids, edge arrays, float weights). Adapters produce that representation:

```
osmnx graph  ──> node-graph adapter ──┐
                                      ├──> CSR arrays ──> routing core (Dijkstra / A* / Yen)
line graph   ──> edge-graph adapter ──┘
```

Consequences, all intended:
- Switching to the line graph for turn restrictions swaps an adapter, not the router.
- The core is trivially testable against small hand-built graphs and property-based random graphs.
- Dijkstra on plain arrays with a binary heap is 10–50x faster than on networkx object graphs;
  the benchmark against the networkx oracle doubles as a performance result.

Package layout: `src/router/core/` (algorithms, arrays only), `src/router/graph/` (OSM download,
caching, adapters, line graph), `src/router/traffic/` (TomTom client, matching, cache),
`src/router/corridor/` (ellipse, k-paths, subgraph extraction), `app/` (Streamlit).

### The two-pass design

Live traffic comes from the **TomTom Traffic API free tier**. The quota does not allow refreshing
a whole city, so traffic is fetched **on demand, only after origin and destination are known**,
and only for a corridor between them:

1. **First pass — static.** Dijkstra over the whole graph using free-flow travel time.
   City scale (~10^5 edges) makes a full-graph Dijkstra per query perfectly fine; do not build
   contraction hierarchies or other speedup structures — overkill at this size, note it in the
   README as the known scaling path.
2. **Corridor — ellipse first, then Yen inside it.**
   - **Ellipse bound, stated correctly.** We accept candidate routes with free-flow time up to
     `(1+epsilon) * t_star`, where `t_star` is the first-pass optimum. Any such route has length
     at most `L_max = (1+epsilon) * t_star * v_max`, where `v_max` is the maximum speed in the
     graph (you cannot cover more distance than time times top speed). Therefore every candidate
     lies inside the ellipse with foci at origin and destination and major axis `L_max`. This is
     a provable containment bound *on the time-based objective we actually optimise* — sizing the
     ellipse by `(1+epsilon)` times the shortest *distance* would be wrong, because a time-optimal
     route (e.g. a ring road) can be much longer in metres than the distance-shortest path.
     `epsilon` configurable, default 0.3. Implement the point-in-ellipse test in projected metres.
   - **Yen's k shortest paths run on the ellipse subgraph, never on the full graph** (k default 4,
     by free-flow time). Yen is many Dijkstra runs with edges removed; restricting it to the
     ellipse turns an expensive step into a cheap one. Buffer the union of the k paths and add it
     to the corridor to capture structurally different alternatives.
3. **Traffic sampling** (see below) only for corridor edges.
4. **Second pass.** Dijkstra on the corridor subgraph with traffic-adjusted weights. The UI shows
   free-flow and traffic-aware routes side by side.

### Traffic layer — TomTom client and map matching

Verify current endpoints and free-tier limits against TomTom's live documentation before coding;
do not assume them.

- Use the **Flow Segment Data** endpoint: given a point, it returns the closest road segment with
  current speed, free-flow speed and the segment polyline.
- **Sampling strategy:** do not call once per OSM edge. Sample the corridor at roughly one probe
  point per ~300 m of corridor length (configurable), taking edge midpoints. This cuts API calls
  by an order of magnitude at negligible accuracy cost.
- **Matching returned polylines to OSM edges:** project both to metres, match by buffered
  geometric overlap **plus a bearing check** (reject candidate edges whose bearing differs from
  the polyline's local bearing by more than ~30 degrees). Without the bearing check, dual
  carriageways get the opposite direction's traffic — the classic silent failure of this step.
- Apply the matched speed as a factor on the affected edges' travel time; edges with no traffic
  data keep free-flow time.
- **Cache** per probe point, key = coordinates quantised to ~50 m, TTL default 5 minutes, so
  nearby repeated queries reuse data.
- **Documented error modes:** opposite-carriageway assignment, vertically stacked roads (bridges,
  underpasses) overlapping in 2D, TomTom segments spanning several OSM edges and vice versa.
  These belong in the README — matching is the fiddliest, least visible part of the project.

### Free-flow speeds

Use `osmnx.add_edge_speeds` and `add_edge_travel_times` rather than hand-rolling imputation:
they fill missing `maxspeed` from per-highway-type means. Document the imputation and its bias
(residential defaults are optimistic). Keep `v_max` for the ellipse bound as the max imputed
speed actually present in the graph.

### Turn restrictions

OSM encodes banned turns as **relations between pairs of ways**, not edge properties, and osmnx
does not fetch or apply them. Implementation route:
- Fetch `type=restriction` relations for the area separately via the Overpass API; map their
  `from`/`via`/`to` members to graph edges.
- Route on the **line graph**: each node is a road segment, each arc a manoeuvre. A banned turn
  is an absent arc; a turn penalty is arc cost. The routing core is unchanged — this is just the
  edge-graph adapter.
- On the line graph, the A* heuristic uses the coordinates of the segment's **head node**; state
  in a docstring why this keeps the heuristic admissible.
- Expect roughly 3–4x node count; measure and report the cost in the benchmark table.

## Algorithms — implement these myself

The point of the project is the algorithms, so **do not** call `networkx.shortest_path` for the
core routing. Implement in `src/router/core/`, over CSR arrays:

- **Dijkstra** with a binary heap.
- **A\*** with the admissible heuristic `great_circle_distance / v_max`, plus a benchmark
  comparing settled-node counts and wall time against plain Dijkstra.
- **Yen's k shortest paths**, built on the above.

`networkx` is the **test oracle only**: property-based tests (`hypothesis`) generate small random
directed graphs and assert my implementations return the same cost as networkx; golden tests run
fixed origin/destination pairs on a cached Verona extract committed as a test fixture (small
bbox, not the whole city). Every mathematical assumption — heuristic admissibility, the ellipse
bound, non-negative weights — gets stated where it is relied upon: these are the parts I must be
able to defend in an interview.

## Stack

- Python 3.12
- `osmnx` / `networkx` for graph construction and as test oracle (not for core routing)
- `shapely` + `pyproj` for projected geometry
- `httpx` for the TomTom client
- Streamlit + `streamlit-folium` (or pydeck) for the map UI
- `pytest` + `hypothesis`; `ruff`, `pre-commit`, GitHub Actions

## Roadmap

1. **Scaffolding** — repo layout, `pyproject.toml`, Makefile, ruff, pre-commit, CI, README skeleton.
2. **Graph layer** — download and cache the OSM network (serialised so startup is fast), project
   it, free-flow speeds and times, CSR adapter. Commit a small bbox extract as a test fixture.
3. **Routing core** — Dijkstra and A\* over CSR arrays, hypothesis tests against the networkx
   oracle, golden tests on the fixture, benchmark table.
4. **Corridor** — ellipse (time-budget bound, projected), Yen on the ellipse subgraph, buffered
   union, subgraph extraction. A debug view rendering the corridor on a map.
5. **Traffic** — TomTom client, probe sampling, polyline-to-edge matching with bearing check,
   TTL cache, second pass. Endpoints and limits verified against live docs first.
6. **Turn restrictions** — Overpass restriction fetch, line-graph adapter, turn penalties,
   line-graph A\* heuristic note, benchmark update.
7. **UI** — Streamlit: pick origin and destination on the map or by search, show free-flow vs
   traffic-aware route side by side, show the corridor, show which edges got live data.
8. **Documentation and benchmarks** — README with a route-comparison screenshot at the top,
   results, the modelling assumptions above, and the error modes of matching.

## Hard constraints

- **The app must run without a TomTom API key.** With no key it falls back to free-flow routing
  and says so in the UI. A project that cannot start without someone else's credentials is dead
  the day the key expires.
- Never commit API keys or `.env`. Cached graphs and traffic caches stay out of git; the only
  committed data is the small test fixture, with its OSM attribution.
- Respect TomTom's terms of use; document the licences for both TomTom and OpenStreetMap data
  (OSM is ODbL — attribution required).
- Every milestone ends in a runnable state.
- Code, comments, docstrings and documentation in English.

## Scope for this session

**Milestone 1 only.** No graph code, no algorithms, no API client yet.

Definition of done: on a clean machine, `make venv` sets up the environment, `make lint` and
`make test` both pass, CI runs the same on push, and the README states what the project will do
and its current status.

## Rules

- Explain design decisions briefly as you go — I want to understand the choices, not just receive files.
- Ask me before anything destructive: force pushes, history rewrites, deleting files I wrote.
- Commit messages in imperative mood, one logical change per commit.
- When a mathematical choice is involved, state the assumption explicitly in a docstring or
  comment at the point of use. These are the parts I need to be able to defend in an interview.
