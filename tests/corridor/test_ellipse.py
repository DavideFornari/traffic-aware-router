"""Unit tests for the ellipse time-budget bound."""

import numpy as np
import pytest

from router.corridor.ellipse import ellipse_l_max, ellipse_l_max_distance, in_ellipse


def test_l_max_scales_with_epsilon_and_v_max():
    assert ellipse_l_max(t_star=100.0, epsilon=0.0, v_max=10.0) == pytest.approx(1000.0)
    assert ellipse_l_max(t_star=100.0, epsilon=0.3, v_max=10.0) == pytest.approx(1300.0)


def test_l_max_rejects_non_positive_inputs():
    with pytest.raises(ValueError):
        ellipse_l_max(t_star=0.0, epsilon=0.3, v_max=10.0)
    with pytest.raises(ValueError):
        ellipse_l_max(t_star=100.0, epsilon=0.3, v_max=0.0)
    with pytest.raises(ValueError):
        ellipse_l_max(t_star=100.0, epsilon=-0.1, v_max=10.0)


def test_l_max_distance_scales_with_epsilon():
    assert ellipse_l_max_distance(straight_line_m=1000.0, epsilon=0.0) == pytest.approx(1000.0)
    assert ellipse_l_max_distance(straight_line_m=1000.0, epsilon=0.3) == pytest.approx(1300.0)


def test_l_max_distance_rejects_non_positive_inputs():
    with pytest.raises(ValueError):
        ellipse_l_max_distance(straight_line_m=0.0, epsilon=0.3)
    with pytest.raises(ValueError):
        ellipse_l_max_distance(straight_line_m=1000.0, epsilon=-0.1)


def test_focus_points_are_always_inside():
    # sum of distances at a focus is just the distance to the other focus.
    focus1, focus2 = (0.0, 0.0), (100.0, 0.0)
    x = np.array([0.0, 100.0])
    y = np.array([0.0, 0.0])
    mask = in_ellipse(x, y, focus1, focus2, l_max=100.0)
    assert mask.all()


def test_midpoint_perpendicular_bisector_boundary():
    # a point directly "above" the midpoint: sum of distances = 2 * hypot(50, h).
    focus1, focus2 = (0.0, 0.0), (100.0, 0.0)
    h = 30.0
    l_max = 2 * np.hypot(50.0, h)
    x = np.array([50.0])
    y = np.array([h])
    assert in_ellipse(x, y, focus1, focus2, l_max)[0]
    assert not in_ellipse(x, y, focus1, focus2, l_max - 1e-6)[0]


def test_far_away_point_is_excluded():
    focus1, focus2 = (0.0, 0.0), (100.0, 0.0)
    x = np.array([5000.0])
    y = np.array([5000.0])
    assert not in_ellipse(x, y, focus1, focus2, l_max=200.0)[0]


def test_vectorised_over_many_points_on_the_major_axis():
    # On the line through both foci, points within [-5, 15] have d1 + d2 <= 20
    # (10 beyond each focus, matching l_max's excess over the focal distance).
    focus1, focus2 = (0.0, 0.0), (10.0, 0.0)
    x = np.linspace(-10, 20, 31)
    y = np.zeros_like(x)
    mask = in_ellipse(x, y, focus1, focus2, l_max=20.0)
    expected = (x >= -5) & (x <= 15)
    np.testing.assert_array_equal(mask, expected)
