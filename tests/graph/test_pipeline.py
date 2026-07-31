"""Golden test: the full load -> prepare -> CSR pipeline on the Verona fixture."""

from pathlib import Path

import numpy as np
import osmnx as ox

from router.graph.csr import build_csr
from router.graph.prepare import prepare_graph

FIXTURE = Path(__file__).parent.parent / "fixtures" / "verona_center.graphml"


def test_pipeline_produces_a_consistent_csr_graph():
    raw = ox.load_graphml(FIXTURE)
    prepared = prepare_graph(raw)
    csr = build_csr(prepared)

    assert csr.n_nodes == prepared.number_of_nodes()
    assert csr.n_edges <= prepared.number_of_edges()  # parallel edges may collapse
    assert np.all(csr.weights > 0)
    assert np.all(np.diff(csr.indptr) >= 0)
    assert csr.indptr[-1] == csr.n_edges
    assert len(csr.edge_keys) == csr.n_edges
