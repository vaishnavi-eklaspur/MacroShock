"""Rule-based rebalancing recommendation (transparent, no black box).

See docs/METHODOLOGY.md section 9.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .portfolio import normalize_weights


@dataclass
class OptimizedRebalance:
    applied: bool
    method: str
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    old_volatility: float
    new_volatility: float
    volatility_change: float
    old_drawdown: float
    new_drawdown: float
    drawdown_improvement: float
    turnover: float                       # sum |w_new - w_old|


def optimize_rebalance(weights: np.ndarray, tickers: list[str],
                       scenario_asset_returns: np.ndarray, cov: np.ndarray,
                       per_asset_cap: float = 0.15) -> OptimizedRebalance:
    """Constrained optimizer: minimize crisis-regime variance without worsening the scenario.

    Solves (SLSQP):
        minimize   wᵀ Σ w                         (crisis-regime portfolio variance)
        subject to Σ w = 1,  0 <= w <= 1,
                   |w_i - w0_i| <= per_asset_cap  (turnover discipline, via bounds)
                   rᵀ w >= rᵀ w0                  (scenario drawdown not made worse)

    This replaces the greedy single-shift heuristic with a genuine constrained optimization -
    the kind of pose-and-solve a risk desk expects. Falls back to `applied=False` if the
    solver cannot improve on the current allocation.
    """
    w0 = normalize_weights(weights)
    r = np.asarray(scenario_asset_returns, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = len(w0)

    old_var = float(w0 @ cov @ w0)
    old_dd = float(r @ w0)

    bounds = [(max(0.0, w0[i] - per_asset_cap), min(1.0, w0[i] + per_asset_cap)) for i in range(n)]
    constraints = [
        {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0), "jac": lambda w: np.ones(n)},
        {"type": "ineq", "fun": lambda w: float(r @ w - old_dd), "jac": lambda w: r},
    ]

    def objective(w):
        return float(w @ cov @ w)

    def objective_grad(w):
        return 2.0 * (cov @ w)

    res = minimize(objective, w0, jac=objective_grad, bounds=bounds,
                   constraints=constraints, method="SLSQP",
                   options={"maxiter": 300, "ftol": 1e-12})

    new_w = res.x if res.success else w0
    new_w = np.clip(new_w, 0.0, None)
    new_w = new_w / new_w.sum()
    new_var = float(new_w @ cov @ new_w)
    new_dd = float(r @ new_w)
    turnover = float(np.abs(new_w - w0).sum())

    old_vol, new_vol = float(np.sqrt(max(old_var, 0))), float(np.sqrt(max(new_var, 0)))
    applied = bool(res.success and new_vol < old_vol - 1e-9 and turnover > 1e-4)

    return OptimizedRebalance(
        applied=applied,
        method="min-variance (SLSQP) s.t. long-only, turnover cap, no drawdown worsening",
        old_weights={t: float(x) for t, x in zip(tickers, w0)},
        new_weights={t: float(x) for t, x in zip(tickers, new_w if applied else w0)},
        old_volatility=old_vol,
        new_volatility=new_vol if applied else old_vol,
        volatility_change=(new_vol - old_vol) if applied else 0.0,
        old_drawdown=old_dd,
        new_drawdown=new_dd if applied else old_dd,
        drawdown_improvement=(new_dd - old_dd) if applied else 0.0,
        turnover=turnover if applied else 0.0,
    )
