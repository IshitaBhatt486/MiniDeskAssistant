"""
Fallback for the `lap` package (used by Ultralytics' ByteTrack for linear assignment).

`lap` is a compiled extension. Some machines refuse to load it, for example Windows with Smart App
Control on ("DLL load failed ... An Application Control policy has blocked this file"). In that case
`install()` registers a stand-in module named `lap` whose `lapjv(cost, extend_cost=True, cost_limit=L)`
gives exactly the same assignment as lap's, solved with scipy's Hungarian solver (or Ultralytics'
own fallback if scipy is missing).

On the Raspberry Pi the real `lap` loads normally and this module does nothing.
"""

from __future__ import annotations

import sys
import types

import numpy as np


def _solve(cost):
    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError:  # pragma: no cover
        from ultralytics.utils.ops import linear_sum_assignment
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
