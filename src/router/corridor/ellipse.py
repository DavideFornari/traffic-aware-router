"""Ellipse-shaped bound on candidate corridor routes.

Both functions operate in projected metres — never raw lat/lon degrees, per
CLAUDE.md's rule that geometric reasoning happens after projection.
"""

from __future__ import annotations

import numpy as np


def ellipse_l_max(t_star: float, epsilon: float, v_max: float) -> float:
    """Major-axis bound on routes with free-flow time up to `(1+epsilon)*t_star`.

    We accept candidate routes with free-flow time at most `(1 + epsilon) *
    t_star`, where `t_star` is the first-pass shortest-time. Since no edge
    exceeds `v_max`, such a route covers at most `time * v_max` metres —
    time bounds distance, not the other way round. So `l_max = (1 +
    epsilon) * t_star * v_max` bounds the length of every accepted route.

    This must be sized from the *time* budget, not `(1 + epsilon)` times the
    shortest *distance*: a time-optimal route (e.g. a ring road) can be far
    longer in metres than the distance-shortest path, so a distance-based
    bound could exclude it.
    """
    if t_star <= 0 or v_max <= 0:
        raise ValueError("t_star and v_max must be positive.")
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative.")
    return (1.0 + epsilon) * t_star * v_max


def in_ellipse(
    x: np.ndarray,
    y: np.ndarray,
    focus1: tuple[float, float],
    focus2: tuple[float, float],
    l_max: float,
) -> np.ndarray:
    """Boolean mask of which `(x, y)` points lie inside (or on) the ellipse.

    Foci are the origin and destination; `l_max` is the major axis from
    `ellipse_l_max`. Uses the focal definition of an ellipse directly — a
    point lies in it iff the sum of its distances to the two foci is at
    most `l_max` — which needs no center, rotation, or semi-axis lengths.
    Every point on a route whose length is at most `l_max` satisfies this,
    since the sum of distances to the two endpoints of any path is at most
    the path's own length (triangle inequality).
    """
    d1 = np.hypot(x - focus1[0], y - focus1[1])
    d2 = np.hypot(x - focus2[0], y - focus2[1])
    return (d1 + d2) <= l_max
