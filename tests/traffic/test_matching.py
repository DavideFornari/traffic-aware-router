"""Unit tests for polyline-to-edge matching: the buffer + bearing check.

Exercises the two documented failure modes directly (see matching.py's
module docstring): opposite-carriageway assignment and buffer-only false
positives, plus the boundary cases around both thresholds.
"""

import pytest

from router.traffic.matching import (
    bearing_deg,
    bearing_difference_deg,
    edge_matches_segment,
    local_bearing_deg,
)


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


# A curved segment: east from (0,0) to (50,0), then a sharp bend north to
# (50,50). Its overall start-to-end bearing is ~45 degrees (northeast), but
# its LOCAL bearing near the start is 90 (due east) and near the end is 0
# (due north) — nothing like the overall bearing at either end.
CURVED_SEGMENT = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)]


def test_local_bearing_near_the_start_is_the_first_legs_bearing():
    assert local_bearing_deg(CURVED_SEGMENT, 25.0, 0.0) == pytest.approx(90.0)


def test_local_bearing_near_the_end_is_the_last_legs_bearing():
    assert local_bearing_deg(CURVED_SEGMENT, 50.0, 25.0) == pytest.approx(0.0)


def test_matches_an_edge_whose_bearing_agrees_with_the_curve_locally_but_not_overall():
    # East-facing edge near the segment's start: local bearing (90) matches,
    # even though the segment's overall bearing (~45) would put it right at
    # the 30-degree default tolerance's edge — a whole-polyline bearing
    # check would reject this valid match.
    assert edge_matches_segment(0.0, 2.0, 50.0, 2.0, CURVED_SEGMENT)


def test_rejects_an_edge_whose_bearing_only_agrees_with_the_curve_far_away():
    # Horizontal (east/west) edge sitting near the segment's *end*, where
    # the local bearing is 0 (north) — should not match, even though this
    # edge's bearing (90) is close to the segment's overall bearing (~45).
    assert not edge_matches_segment(48.0, 25.0, 52.0, 25.0, CURVED_SEGMENT)
