# CLAUDE.md — working guide for traffic-aware-router

## Project state

All 8 roadmap milestones are **complete** (scaffolding → graph layer → routing core →
corridor → traffic → turn restrictions → Streamlit UI → docs/benchmarks). The repo is in
maintenance/extension mode: the job of any session is to improve or extend it **without
breaking the invariants below**. `README.md` is the public, complete description of what
was built and why; this file is the working contract for changing it.

Audience: this is a public portfolio repo read by recruiters and technical interviewers.
Code quality, docstrings, commit history, and repo hygiene are part of the product.
Every commit leaves lint green, tests green, and the app runnable — no exceptions.

## Environment and verification loop

- Windows 11. The venv is `.venv` (CPython 3.14). `make` is not available in every shell
  here — prefer the underlying commands:
  - Tests: `.venv/Scripts/python.exe -m pytest -q` (134 tests, ~4 s; all must pass)
  - Lint: `.venv/Scripts/python.exe -m ruff check .` (`--fix` for autofixable)
  - Format: `.venv/Scripts/python.exe -m ruff format .`
  - App: `.venv/Scripts/python.exe -m streamlit run app/main.py`
- Run lint + format + full tests **before every commit**. CI (`.github/workflows/ci.yml`,
  ubuntu / py3.12, installs `.[dev]` only) runs the same — so tests must never import
  `folium`, `streamlit`, or `matplotlib` (those live in the `viz`/`app` extras).
- The pre-commit hook runs ruff and may modify files. When a commit fails with
  "files were modified by this hook", `git add` the fixed files and commit again.
- Git prints `LF will be replaced by CRLF` warnings on this machine — harmless, ignore.
- Network access works (Overpass, Nominatim, TomTom docs). Downloads are cached under
  `data/cache/` and osmnx's `cache/` — both gitignored; never commit them, and never
  commit an API key or `.env`. `TOMTOM_API_KEY` comes from the environment only.

## Invariants — do not break these

1. **Layering: the routing core never sees OSM, networkx, or TomTom.** Everything in
   `src/router/core/` operates on CSR arrays (`indptr`/`indices`/`weights`) plus plain
   numpy coordinate arrays. Adapters (`graph/csr.py`, `graph/line_graph.py`) are the only
   crossing point. A change that makes the core import networkx is wrong by construction.
2. **All geometry in projected metres.** Ellipse, buffers, matching, quantised cache keys —
   never in raw lat/lon degrees. `prepare_graph` projects once (UTM via osmnx) and stashes
   `lat`/`lon` on nodes *only* for the A* heuristic and display.
3. **The app must run with no TomTom key.** `TomTomClient(api_key=None)` is a no-op
   returning `None`; everything downstream treats "no traffic data" as the normal case and
   falls back to free-flow, visibly (a warning banner, not silence). Any new traffic
   feature must preserve this path and its tests.
4. **networkx is the test oracle only.** Property tests (`hypothesis`) compare our
   algorithms against networkx on random graphs; golden tests run both on the committed
   fixture (`tests/fixtures/verona_center.graphml`, the only committed data, ODbL
   attribution in `tests/fixtures/README.md`). New algorithms get the same triad:
   unit tests on hand-built graphs, a property test against an oracle, a golden test.
5. **Mathematical assumptions stated at the point of use.** Non-negative weights
   (dijkstra), A* admissibility (astar, and again for the line graph's head-node rule),
   the ellipse time-budget bound (ellipse.py), the bearing check's purpose (matching.py).
   If a change relies on a new assumption, it goes in a docstring where it's relied on
   *and* in the README section. These are what the author must defend in interviews.
6. **The area is configuration.** Nothing outside `graph/config.py` may hardcode Verona;
   `verona()` is only the default. Any OSM place name or bbox must keep working.
7. **HTTP is faked in tests.** No test makes a real network call: `httpx` responses are
   constructed, osmnx download functions are monkeypatched, the UI is exercised with
   `streamlit.testing.v1.AppTest`. Keep it that way — CI has no quota to spend.

## File map

```
src/router/core/       dijkstra.py, astar.py, yen.py, geometry.py — arrays only
src/router/graph/      config.py, download.py (GraphML disk cache), prepare.py,
                       csr.py (node-graph adapter), restrictions.py (Overpass fetch +
                       resolve), line_graph.py (turn-restriction adapter +
                       route_on_line_graph, a multi-source/multi-target query helper)
src/router/corridor/   ellipse.py, subgraph.py (Subgraph optionally carries edge_keys),
                       buffer.py, pipeline.py (build_corridor),
                       restricted_second_pass.py (turn-restriction-aware second pass —
                       builds a corridor-scoped line graph and routes on it)
src/router/traffic/    client.py (TomTom), sampling.py, matching.py, cache.py,
                       pipeline.py (apply_traffic)
app/                   main.py (Streamlit; all st.*/folium.* code), helpers.py (pure,
                       unit-tested logic — keep new UI logic here, not in main.py)
scripts/               benchmark_core.py, benchmark_line_graph.py, debug_corridor.py,
                       generate_screenshot.py — regenerate README numbers/images
tests/                 mirrors src layout; fixtures/ holds the committed extract
```

Convention: `app/main.py` and `scripts/*` use `sys.path.insert` because only `src/` is an
installed package. Keep new scripts consistent with the existing ones.

## Externally verified facts (re-verify before relying on them)

Checked against live docs on 2026-07-31; TomTom can change either at any time:
- Flow Segment Data endpoint: `GET https://api.tomtom.com/traffic/services/4/
  flowSegmentData/{style}/{zoom}/json?key=...&point={lat},{lon}&unit=kmph`.
- Free tier: 20,000 requests/month, no credit card.

Any work touching the TomTom client starts by re-checking docs.tomtom.com — do not assume.

## Commit conventions

- Imperative mood, one logical change per commit, body explains the *why*.
- Ask before anything destructive: force pushes, history rewrites, deleting user-written
  files. Never push without being asked.
- Explain design decisions in the conversation as you go — the author wants to understand
  choices, not just receive files.

## Improvement backlog (from full code review, 2026-08-01)

Prioritised; each item is safe to pick up independently. Re-run the relevant benchmark or
tests after each, and update README if behaviour or numbers change.

**Done (2026-08-01, same-day follow-up session)** — all three former P1 items:
1. ~~Turn restrictions built but not wired in~~ — fixed. `line_graph.py` gained
   `route_on_line_graph` (multi-source/multi-target Dijkstra via a virtual super-source
   node appended to the CSR arrays — no change to the core `dijkstra` itself); new
   `corridor/restricted_second_pass.py` builds a small line graph from just the corridor's
   (traffic-adjusted) edges and routes on it. `app/main.py`'s `load_area` now fetches +
   resolves restrictions once per area (degrades to `[]` on Overpass failure, same
   resilience pattern as the no-TomTom-key path); the second pass uses them, the free-flow
   first pass deliberately doesn't (stated in-app and in README — see "Turn restrictions").
   Tested with the full triad (unit/property/golden) on `route_on_line_graph` and on the
   corridor integration; verified end-to-end with `AppTest` (2,559 restrictions applied on
   Verona, zero exceptions).
2. ~~Bearing check used the whole polyline~~ — fixed. `matching.py` gained
   `local_bearing_deg`: projects onto the polyline, finds the nearest vertex pair, uses
   just that pair's bearing. Verified the fix changes real outcomes (a curved-segment case
   that the old whole-polyline check would wrongly reject now correctly matches).
3. ~~Streamlit results vanished on rerun~~ — fixed. `app/main.py` resolves everything to
   plain lat/lon in `st.session_state.result` at compute time; a new `render_result()` runs
   on every rerun, not just the one where the button was clicked.

Also fixed in passing: `.pre-commit-config.yaml` pinned ruff at `v0.6.9` while the venv/CI
ran `0.16.1` — the two versions disagreed on import-block ordering and were flip-flopping
two files' formatting back and forth on every commit. Pinned to `v0.16.1` to match.

**P2 — performance (measure before/after; scripts exist)**
4. `app/helpers.py::nearest_node` is a pure-Python loop over all ~41k nodes with a
   haversine call each — two calls per query. Vectorise with numpy (or KDTree on
   projected coords, which is also more correct than haversine at city scale).
5. `_edge_position` (duplicated in `core/yen.py` and `traffic/pipeline.py`) is a linear
   scan; row indices are sorted, so `np.searchsorted` works. Deduplicate into one helper.
6. Yen copies the full weight array per spur (`weights.copy()` — O(E) each); the
   non-negativity check in `dijkstra` also rescans O(E) per spur call. Hoist the check;
   restore-in-place instead of copying if profiling justifies it.
7. The corridor layer in `app/main.py` adds one `folium.PolyLine` per edge (thousands of
   objects; slow render). Batch into a single GeoJson/MultiLineString layer.

**P3 — hygiene, docs, robustness**
8. `Makefile` `venv` target installs only `.[dev]`; README's "Try it" needs
   `.[dev,viz,app]`. Align them (e.g. a `make app` target) so both documented paths work.
9. `app/__init__.py` still says "Implemented in Milestone 7" — stale scaffold comment.
10. `download.py::_cache_key` ignores the osmnx version; a graph cached by one osmnx
    major version may deserialize oddly under another. Include `ox.__version__` in the key.
11. `graph_bbox` silently assumes an *unprojected* graph (y/x are degrees). Add a CRS
    guard or assertion — passing a projected graph would produce a nonsense Overpass bbox.
12. Document in README's modelling assumptions: the ellipse containment bound is proved
    for the *free-flow* objective; the traffic-optimal route can in principle leave the
    corridor. The corridor is a deliberate approximation for the second pass.
13. CI matrix: dev machine runs 3.14, CI only 3.12. Add 3.13/3.14 to catch version drift.
14. `geocode` in `app/main.py` is unbiased global Nominatim — searching "Piazza Bra" can
    land in another city. Bias the query with the selected area name.
15. README's line-graph benchmark shows 91,758 line nodes vs 91,074 node-graph CSR edges
    without explaining the difference (CSR collapses parallel edges; the line graph keeps
    them). One clarifying sentence avoids a sharp-eyed reviewer reading it as an error.
