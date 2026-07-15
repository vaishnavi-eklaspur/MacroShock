"""Rule-based rebalancing recommendation (transparent, no black box).

See docs/METHODOLOGY.md section 9.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .portfolio import normalize_weights, portfolio_volatility


@dataclass
class RebalanceRecommendation:
    applied: bool                       # True only if it strictly improves the drawdown
    reason: str
    from_ticker: str | None
    to_ticker: str | None
    shift: float                        # weight moved (fraction)
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    old_drawdown: float                 # scenario portfolio return (negative = loss)
    new_drawdown: float
    drawdown_improvement: float         # new - old (positive = less loss)
    old_volatility: float
    new_volatility: float
    volatility_change: float            # new - old (negative = less risk)


def recommend_rebalance(weights: np.ndarray, tickers: list[str],
                        scenario_asset_returns: np.ndarray, cov: np.ndarray,
                        max_shift: float = 0.15) -> RebalanceRecommendation:
    """Shift weight from the biggest scenario loss driver into the best available hedge.

    Steps:
      1. Per-holding scenario P&L contribution = w_i * r_i^scenario.
      2. Loss driver = holding with the most negative contribution.
      3. Hedge = holding with the highest scenario return (best cushion) that is not the driver.
      4. Move min(max_shift, w_driver) of weight; recompute drawdown and volatility.
      5. Only recommend if the scenario drawdown strictly improves.
    """
    w = normalize_weights(weights)
    r = np.asarray(scenario_asset_returns, dtype=float)
    cov = np.asarray(cov, dtype=float)

    contribution = w * r
    driver = int(np.argmin(contribution))               # most negative P&L contribution

    # Best hedge: highest scenario return among the other holdings.
    candidates = [i for i in range(len(w)) if i != driver]
    hedge = max(candidates, key=lambda i: r[i])

    old_dd = float(w @ r)
    old_vol = portfolio_volatility(w, cov)
    old_weights = {t: float(x) for t, x in zip(tickers, w)}

    shift = float(min(max_shift, w[driver]))
    new_w = w.copy()
    new_w[driver] -= shift
    new_w[hedge] += shift

    new_dd = float(new_w @ r)
    new_vol = portfolio_volatility(new_w, cov)
    improvement = new_dd - old_dd

    applied = improvement > 1e-9
    reason = (
        f"Shift {shift:.0%} from {tickers[driver]} (largest scenario loss driver) "
        f"into {tickers[hedge]} (best scenario cushion)."
        if applied else
        "No single-trade shift improves the scenario drawdown; portfolio is already "
        "well-positioned for this scenario."
    )

    return RebalanceRecommendation(
        applied=applied,
        reason=reason,
        from_ticker=tickers[driver] if applied else None,
        to_ticker=tickers[hedge] if applied else None,
        shift=shift if applied else 0.0,
        old_weights=old_weights,
        new_weights={t: float(x) for t, x in zip(tickers, (new_w if applied else w))},
        old_drawdown=old_dd,
        new_drawdown=new_dd if applied else old_dd,
        drawdown_improvement=improvement if applied else 0.0,
        old_volatility=old_vol,
        new_volatility=new_vol if applied else old_vol,
        volatility_change=(new_vol - old_vol) if applied else 0.0,
    )
