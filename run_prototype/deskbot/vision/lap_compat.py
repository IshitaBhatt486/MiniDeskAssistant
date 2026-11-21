"""
Linear assignment with `lap`'s semantics, solved in numpy (20 Nov 2026: the robot installs neither `lap` nor scipy).

`lapjv()` is what deskbot/vision/bytetrack.py uses. `install()` is only for the old Ultralytics detector
(detector.YoloDetector, the .pt fallback on a laptop): it registers this as the `lap` module if the real one is
missing or blocked.

History: `lap` was the package Ultralytics' ByteTrack used for linear assignment.

`lap` is a compiled extension. Some machines refuse to load it, for example Windows with Smart App
Control on ("DLL load failed ... An Application Control policy has blocked this file"). In that case
`install()` registers a stand-in module named `lap` whose `lapjv(cost, extend_cost=True, cost_limit=L)`
gives exactly the same assignment as lap's, solved with linear_sum_assignment() below (numpy Hungarian;
it used scipy's until 20 Nov 2026).

On the Raspberry Pi the real `lap` loads normally and this module does nothing.
"""

from __future__ import annotations

import sys
import types

import numpy as np


def linear_sum_assignment(cost):
    """Minimum-cost assignment of a rectangular cost matrix, numpy only (20 Nov 2026; was scipy's).
    Same contract as scipy.optimize.linear_sum_assignment: (rows sorted ascending, cols), min(n, m) pairs.
    Shortest augmenting path Hungarian algorithm with potentials (Kuhn-Munkres / Jonker-Volgenant style),
    O(n^2 m); the tracker's matrices are a few dozen at most, so this takes well under a millisecond."""
    cost = np.asarray(cost, dtype=float)
    if cost.size == 0:
        return np.zeros(0, int), np.zeros(0, int)
    transposed = cost.shape[0] > cost.shape[1]
    a = cost.T if transposed else cost                  # n rows <= m cols
    n, m = a.shape
    u, v = np.zeros(n + 1), np.zeros(m + 1)
    p = np.zeros(m + 1, int)                            # p[j] = row (1-based) matched to column j; 0 = free
    way = np.zeros(m + 1, int)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv = np.full(m + 1, np.inf)
        used = np.zeros(m + 1, bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            cur = a[i0 - 1] - u[i0] - v[1:]             # reduced costs from row i0 to every column
            free = ~used[1:]
            better = free & (cur < minv[1:])
            minv[1:][better] = cur[better]
            way[1:][better] = j0
            cand = np.where(free, minv[1:], np.inf)
            j1 = int(np.argmin(cand)) + 1
            delta = cand[j1 - 1]
            u[p[used]] += delta
            v[used] -= delta
            minv[1:][free] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:                                       # flip the augmenting path
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    cols = np.flatnonzero(p[1:])
    rows = p[1:][cols] - 1
    if transposed:
        rows, cols = cols, rows
    order = np.argsort(rows)
    return rows[order], cols[order]


def _solve(cost):
    return linear_sum_assignment(cost)


def lapjv(cost, extend_cost=True, cost_limit=np.inf, return_cost=True):
    """Same contract as lap.lapjv: returns (total_cost, x, y) with x[row] = col or -1, y[col] = row or -1.

    With a finite cost_limit, lap pads the problem so that leaving a row or column unmatched costs
    cost_limit / 2. Pairs costing more than cost_limit are therefore never chosen. The same padding
    is built here."""
    cost = np.asarray(cost, dtype=float)
    n, m = cost.shape
    x, y = np.full(n, -1, int), np.full(m, -1, int)
    if n == 0 or m == 0:
        return (0.0, x, y) if return_cost else (x, y)
    if np.isfinite(cost_limit):
        big = max(1e6, float(np.abs(cost).max()) * 10 + cost_limit * 10)
        half = cost_limit / 2.0
        a = np.full((n + m, n + m), big)
        a[:n, :m] = cost
        a[:n, m:][np.arange(n), np.arange(n)] = half   # row i left unmatched
        a[n:, :m][np.arange(m), np.arange(m)] = half   # column j left unmatched
        a[n:, m:] = 0.0
        rows, cols = _solve(a)
        for r, c in zip(rows, cols):
            if r < n and c < m:
                x[r], y[c] = c, r
    else:
        rows, cols = _solve(cost)
        x[rows], y[cols] = cols, rows
    if not return_cost:
        return x, y
    total = float(sum(cost[i, x[i]] for i in range(n) if x[i] >= 0))
    return total, x, y


def install():
    """Use the real `lap` if it loads, otherwise register this stand-in. Returns 'lap' or 'scipy'."""
    try:
        import lap  # noqa: F401
        assert lap.__version__
        return "lap"
    except Exception:
        mod = types.ModuleType("lap")
        mod.lapjv = lapjv
        mod.__version__ = "0.5.12-deskbot-compat"
        sys.modules["lap"] = mod
        return "scipy"
