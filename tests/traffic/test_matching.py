"""Unit tests for polyline-to-edge matching: the buffer + bearing check.

Exercises the two documented failure modes directly (see matching.py's
module docstring): opposite-carriageway assignment and buffer-only false
positives, plus the boundary cases around both thresholds.
"""

import pytest

from router.traffic.matching import bearing_deg, bearing_difference_deg, edge_matches_segment


def test_bearing_of_eastward_edge_is_90_degrees():
    # +y is "north" in the projected CRS convention this module uses.
    assert bearing_deg(0, 0, 100, 0) == pytest.approx(90.0)


def test_bearing_of_northward_edge_is_0_degrees():
    assert bearing_deg(0, 0, 0, 100) == pytest.approx(0.0)


def test_bearing_difference_wraps_around_0_360():
    assert bearing_difference_deg(5.0, 355.0) == pytest.approx(10.0)


def test_bearing_difference_of_opposite_directions_is_180():
    assert bearing_difference_deg(0.0, 180.0) == pytest.approx(180.0)


def test_matches_a_segment_running_alongside_and_parallel():
    # edge and segment both run east, segment offset 5m north.
    assert edge_matches_segment(0, 0, 100, 0, [(0, 5), (100, 5)])


def test_rejects_opposite_carriageway_despite_being_close():
    # segment runs west (reverse direction), just 2m away: the classic
    # dual-carriageway silent failure this bearing check exists to catch.
    assert not edge_matches_segment(0, 0, 100, 0, [(100, 2), (0, 2)])


def test_rejects_segment_outside_the_buffer():
    # same direction, but 50m away — too far for a 15m buffer.
    assert not edge_matches_segment(0, 0, 100, 0, [(0, 50), (100, 50)], buffer_m=15.0)


def test_accepts_segment_just_inside_a_custom_buffer():
    assert edge_matches_segment(0, 0, 100, 0, [(0, 40), (100, 40)], buffer_m=50.0)


def test_rejects_a_perpendicular_segment():
    # a cross-street's segment overlaps geometrically but runs perpendicular.
    assert not edge_matches_segment(0, 0, 100, 0, [(50, -50), (50, 50)])


def test_bearing_tolerance_is_configurable():
    # ~11 degree bearing difference, well within the 15m default buffer:
    # accepted at the default 30deg tolerance, rejected once tightened to 10.
    segment = [(0, 0), (100, 20)]
    assert edge_matches_segment(0, 0, 100, 0, segment, max_bearing_diff_deg=30.0)
    assert not edge_matches_segment(0, 0, 100, 0, segment, max_bearing_diff_deg=10.0)


def test_rejects_a_degenerate_single_point_segment():
    assert not edge_matches_segment(0, 0, 100, 0, [(0, 0)])
