# Traffic-aware router

A router that computes the best path between two points on a real road network, weighting edges
by both free-flow travel time and live traffic. Default area is Verona, Italy, but the area is
configuration — any OpenStreetMap place name or bounding box works.

This is a portfolio project focused on **modelling and algorithms**, not data plumbing: Dijkstra,
A*, and Yen's k-shortest-paths are implemented from scratch over a compact array-based graph
representation, with `networkx` used only as a correctness oracle in tests.

## Status

**Milestone 1 — scaffolding.** Repo layout, dependency management, linting, and CI are in place.
No graph loading, routing, or traffic code yet — see the roadmap below.

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

1. Scaffolding *(this milestone)*
2. Graph layer — OSM download, caching, CSR adapter, test fixture
3. Routing core — Dijkstra, A*, hypothesis + golden tests, benchmark
4. Corridor — ellipse bound, Yen on the ellipse subgraph
5. Traffic — TomTom client, probe sampling, matching, second pass
6. Turn restrictions — line graph, turn penalties
7. UI — Streamlit map with free-flow vs traffic-aware comparison
8. Documentation and benchmarks
