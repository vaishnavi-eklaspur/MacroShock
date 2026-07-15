"""Backtest: model-predicted vs. realized crisis returns.

This is the honest validation the model needs. The factor-shock engine PREDICTS each
asset's return under a scenario; we compare that to INDEPENDENT realized crisis returns
(loaded from documented market history, not generated from the model). Reported per-asset
and aggregated over a set of test portfolios, with standard error metrics.

If a "stress engine" cannot approximately reproduce 2008/2020, it is decoration. This
module lets a reviewer check that it can - and see exactly where it misses.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .factors import scenario_asset_returns
from .portfolio import normalize_weights


def _test_portfolios(tickers: list[str]) -> dict[str, dict[str, float]]:
    """A small panel of representative allocations to backtest across."""
    n = len(tickers)
    equal = {t: 1.0 / n for t in tickers}
    balanced = {"SPY": 0.40, "IEF": 0.20, "LQD": 0.20, "GLD": 0.10, "DBC": 0.10}
    sixty_forty = {"SPY": 0.60, "IEF": 0.40}
    all_equity = {"SPY": 1.0}
    out = {"Equal weight": equal, "Balanced 40/20/20/10/10": balanced,
           "60/40": sixty_forty, "All equity": all_equity}
    # keep only known tickers
    return {name: {t: w for t, w in wts.items() if t in tickers} for name, wts in out.items()}


def backtest_scenario(assets: pd.DataFrame, tickers: list[str], shocks: dict[str, float],
                      realized: dict[str, float]) -> dict:
    """Compare predicted vs realized for one scenario, per-asset and per-portfolio."""
    predicted = scenario_asset_returns(assets, shocks)          # aligned to assets order
    pred_map = {t: float(p) for t, p in zip(tickers, predicted)}

    per_asset = []
    errs = []
    for t in tickers:
        if t not in realized:
            continue
        pred, real = pred_map[t], realized[t]
        per_asset.append({"ticker": t, "predicted": pred, "realized": real,
                          "error": pred - real, "abs_error": abs(pred - real)})
        errs.append(pred - real)
    errs = np.array(errs) if errs else np.array([0.0])

    portfolios = []
    for name, wts in _test_portfolios(tickers).items():
        common = [t for t in wts if t in realized]
        if not common:
            continue
        w = normalize_weights(np.array([wts[t] for t in common]))
        pred_dd = float(w @ np.array([pred_map[t] for t in common]))
        real_dd = float(w @ np.array([realized[t] for t in common]))
        portfolios.append({"portfolio": name, "predicted_drawdown": pred_dd,
                           "realized_drawdown": real_dd, "error": pred_dd - real_dd})

    return {
        "per_asset": per_asset,
        "per_portfolio": portfolios,
        "mae": float(np.mean(np.abs(errs))),
        "rmse": float(np.sqrt(np.mean(errs ** 2))),
    }


def backtest_all(assets: pd.DataFrame, tickers: list[str], scenarios: dict[str, dict],
                 realized_all: dict[str, dict[str, float]]) -> dict:
    """Run the backtest across every scenario that has realized data."""
    results = {}
    all_errs = []
    for scenario_id, realized in realized_all.items():
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            continue
        r = backtest_scenario(assets, tickers, scenario["shocks"], realized)
        r["scenario_name"] = scenario["name"]
        results[scenario_id] = r
        all_errs.extend([a["error"] for a in r["per_asset"]])
    all_errs = np.array(all_errs) if all_errs else np.array([0.0])
    return {
        "scenarios": results,
        "overall_mae": float(np.mean(np.abs(all_errs))),
        "overall_rmse": float(np.sqrt(np.mean(all_errs ** 2))),
        "note": "Predicted = factor-shock model; Realized = documented crisis returns "
                "(independent of the model).",
    }
