# Test fixtures

`verona_center.graphml` — a small drive-network extract around Piazza Bra,
Verona, Italy (bbox `10.988, 45.434, 10.999, 45.442`, `west, south, east,
north`), downloaded via `osmnx.graph_from_bbox` with `network_type="drive"`.
66 nodes, 126 edges after osmnx's default topological simplification.

Raw, unprojected, no speeds or travel times attached — golden tests run the
full `load → prepare_graph → build_csr` pipeline on it, the same as
production code would on a larger extract.

Contains data © OpenStreetMap contributors, licensed under the Open
Database License (ODbL): https://www.openstreetmap.org/copyright
