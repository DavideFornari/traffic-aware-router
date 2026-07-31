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
                       resolve), line_graph.py (turn-restriction adapter)
src/router/corridor/   ellipse.py, subgraph.py, buffer.py, pipeline.py (build_corridor)
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

**P1 — functional gaps**
1. **Turn restrictions are built but not wired in.** `build_line_graph` is complete and
   tested, but neither `corridor/pipeline.py` nor `app/main.py` uses it — user-facing
   routing ignores restrictions. Integrate (fetch+resolve at area load, route the second
   pass on the line graph) or state the gap prominently in README's limitations. Verified:
   no import of `line_graph` outside `src/router/graph/` and its tests/benchmark.
2. **Bearing check uses the whole polyline, not the local bearing.** The original spec
   says local bearing; `matching.py::edge_matches_segment` compares against the segment's
   overall start→end bearing, which misjudges long curved TomTom segments. Fix: bearing of
   the polyline sub-segment nearest the edge midpoint. Add a curved-segment test case.
3. **Route results vanish on any Streamlit rerun.** `app/main.py` gates results behind
   `st.button(...)`, so a map click or widget change erases the computed comparison.
   Persist the last result in `st.session_state` and re-render it.

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
