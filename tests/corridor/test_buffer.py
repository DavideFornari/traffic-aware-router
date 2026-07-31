"""Unit tests for the buffered union of candidate paths."""

import numpy as np

from router.corridor.buffer import buffered_path_union, nodes_in_polygon


def test_no_paths_yields_no_polygon():
    x = np.array([0.0, 1.0])
    y = np.array([0.0, 1.0])
    assert buffered_path_union([], x, y, buffer_m=10.0) is None


def test_single_hop_path_is_skipped_as_unbufferable():
    x = np.array([0.0, 1.0])
    y = np.array([0.0, 1.0])
    assert buffered_path_union([[0]], x, y, buffer_m=10.0) is None


def test_straight_line_path_buffer_contains_nearby_points_and_excludes_far_ones():
    # a horizontal path from (0,0) to (100,0), buffered by 10 metres.
    x = np.array([0.0, 100.0, 50.0, 50.0])
    y = np.array([0.0, 0.0, 5.0, 50.0])
    polygon = buffered_path_union([[0, 1]], x, y, buffer_m=10.0)

    assert polygon is not None
    mask = nodes_in_polygon(x, y, polygon)
    assert mask[0]  # path endpoint itself
    assert mask[1]  # path endpoint itself
    assert mask[2]  # 5m off the path, within the 10m buffer
    assert not mask[3]  # 50m off the path, outside the buffer


def test_nodes_in_polygon_returns_all_false_for_no_polygon():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])
    mask = nodes_in_polygon(x, y, None)
    assert mask.shape == (3,)
    assert not mask.any()
