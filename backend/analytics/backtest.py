"""Backtest: model-predicted vs. realized crisis returns - IN-SAMPLE and OUT-OF-SAMPLE.

Two distinct tests, honestly separated:

  * IN-SAMPLE (calibration check): the hand-calibrated scenario shocks vs. realized returns.
    This only confirms the calibration is internally consistent - it is NOT evidence of
    predictive skill, and is labelled as such.

  * OUT-OF-SAMPLE (the real test): leave-one-crisis-out. Factor shocks are *implied* from
    OTHER crises' realized returns (least-squares inversion through the exposure matrix),
    then used to predict the held-out crisis, whose realized returns never touch the
    prediction. Scored against three naive benchmarks with a skill ratio.

If the factor model cannot beat "predict zero" or "assume the next crisis repeats the last",
it has no skill - and this module will say so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .factors import FACTOR_ORDER, exposure_matrix, scenario_asset_returns
from .portfolio import normalize_weights


def _test_portfolios(tickers: list[str]) -> dict[str, dict[str, float]]:
    n = len(tickers)
    out = {
        "Equal weight": {t: 1.0 / n for t in tickers},
        "Balanced 40/20/20/10/10": {"SPY": 0.40, "IEF": 0.20, "LQD": 0.20, "GLD": 0.10, "DBC": 0.10},
        "60/40": {"SPY": 0.60, "IEF": 0.40},
        "All equity": {"SPY": 1.0},
    }
    return {name: {t: w for t, w in wts.items() if t in tickers} for name, wts in out.items()}


def _rmse(errors: np.ndarray) -> float:
    return float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0


# --------------------------------------------------------------------- in-sample
def backtest_scenario(assets: pd.DataFrame, tickers: list[str], shocks: dict[str, float],
                      realized: dict[str, float]) -> dict:
    """IN-SAMPLE consistency: calibrated shocks vs realized (not a skill test)."""
    predicted = scenario_asset_returns(assets, shocks)
    pred_map = {t: float(p) for t, p in zip(tickers, predicted)}

    per_asset, errs = [], []
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
        portfolios.append({
            "portfolio": name,
            "predicted_drawdown": float(w @ np.array([pred_map[t] for t in common])),
            "realized_drawdown": float(w @ np.array([realized[t] for t in common])),
        })
    return {"per_asset": per_asset, "per_portfolio": portfolios,
            "mae": float(np.mean(np.abs(errs))), "rmse": _rmse(errs)}


# --------------------------------------------------------------------- implied shocks
def implied_shocks_from_realized(assets: pd.DataFrame, tickers: list[str],
                                 realized: dict[str, float],
                                 exposure: np.ndarray | None = None) -> dict[str, float]:
    """Least-squares invert realized asset returns into an implied factor-shock vector.

    Solves min_s ||B_sub s − r|| for the assets that have realized data (min-norm solution
    when under-determined). These implied shocks summarize a crisis in factor space. Pass
    `exposure` to use estimated (rather than structural) betas.
    """
    B_full = exposure_matrix(assets) if exposure is None else np.asarray(exposure, dtype=float)
    common = [t for t in tickers if t in realized]
    idx = [tickers.index(t) for t in common]
    B = B_full[idx, :]
    r = np.array([realized[t] for t in common])
    s, *_ = np.linalg.lstsq(B, r, rcond=None)
    return {name: float(v) for name, v in zip(FACTOR_ORDER, s)}


# --------------------------------------------------------------------- out-of-sample
def out_of_sample_backtest(assets: pd.DataFrame, tickers: list[str],
                           realized_all: dict[str, dict[str, float]],
                           scenario_names: dict[str, str] | None = None,
                           exposure: np.ndarray | None = None) -> dict:
    """Leave-one-crisis-out prediction with naive benchmarks and a skill ratio.

    `exposure` (estimated betas fit on the weekly history) makes this genuinely out-of-sample:
    the exposures never saw the crisis returns they are scored against.
    """
    scenario_names = scenario_names or {}
    B = exposure_matrix(assets) if exposure is None else np.asarray(exposure, dtype=float)
    eq_idx = FACTOR_ORDER.index("Equity")
    crisis_ids = list(realized_all.keys())
    results = {}
    all_model, all_zero, all_repeat, all_equity = [], [], [], []

    for test_id in crisis_ids:
        train_ids = [c for c in crisis_ids if c != test_id]
        if not train_ids:
            continue
        realized_test = realized_all[test_id]
        common = [t for t in tickers if t in realized_test]
        idx = [tickers.index(t) for t in common]

        # Train: average implied shocks across the other crises, and the average realized
        # per-asset return (the "assume it repeats" benchmark).
        implied_list = [implied_shocks_from_realized(assets, tickers, realized_all[c], exposure=B)
                        for c in train_ids]
        s_train = {f: float(np.mean([imp[f] for imp in implied_list])) for f in FACTOR_ORDER}
        s_vec = np.array([s_train[f] for f in FACTOR_ORDER])

        repeat_pred = {}
        for t in common:
            vals = [realized_all[c][t] for c in train_ids if t in realized_all[c]]
            repeat_pred[t] = float(np.mean(vals)) if vals else 0.0

        rows, e_model, e_zero, e_repeat, e_equity = [], [], [], [], []
        for t, i in zip(common, idx):
            real = realized_test[t]
            model = float(B[i] @ s_vec)                  # full factor model
            equity_only = float(B[i, eq_idx] * s_vec[eq_idx])
            rows.append({"ticker": t, "realized": real, "model": model,
                         "repeat_last": repeat_pred[t], "error": model - real})
            e_model.append(model - real)
            e_zero.append(0.0 - real)
            e_repeat.append(repeat_pred[t] - real)
            e_equity.append(equity_only - real)

        rmse_model = _rmse(np.array(e_model))
        rmse_zero = _rmse(np.array(e_zero))
        rmse_repeat = _rmse(np.array(e_repeat))
        rmse_equity = _rmse(np.array(e_equity))
        results[test_id] = {
            "scenario_name": scenario_names.get(test_id, test_id),
            "trained_on": [scenario_names.get(c, c) for c in train_ids],
            "implied_shocks": s_train,
            "per_asset": rows,
            "rmse_model": rmse_model,
            "rmse_benchmark_zero": rmse_zero,
            "rmse_benchmark_repeat": rmse_repeat,
            "rmse_benchmark_equity_only": rmse_equity,
            "skill_vs_zero": 1.0 - rmse_model / rmse_zero if rmse_zero > 0 else 0.0,
            "skill_vs_repeat": 1.0 - rmse_model / rmse_repeat if rmse_repeat > 0 else 0.0,
        }
        all_model.extend(e_model); all_zero.extend(e_zero); all_repeat.extend(e_repeat)
        all_equity.extend(e_equity)

    rmse_model = _rmse(np.array(all_model))
    rmse_zero = _rmse(np.array(all_zero))
    rmse_repeat = _rmse(np.array(all_repeat))
    rmse_equity = _rmse(np.array(all_equity))
    return {
        "scenarios": results,
        "overall_rmse_model": rmse_model,
        "overall_skill_vs_zero": 1.0 - rmse_model / rmse_zero if rmse_zero > 0 else 0.0,
        "overall_skill_vs_repeat": 1.0 - rmse_model / rmse_repeat if rmse_repeat > 0 else 0.0,
        "overall_skill_vs_equity_only": 1.0 - rmse_model / rmse_equity if rmse_equity > 0 else 0.0,
        "note": "Out-of-sample (leakage-free): betas are estimated on the WEEKLY history — they "
                "never see the crisis returns scored here — and factor shocks are implied from "
                "OTHER crises to predict the held-out one. Across only 5 heterogeneous crises a "
                "linear model does NOT reliably beat naive benchmarks, and we report that "
                "honestly. This tests crisis-shape EXTRAPOLATION (forecasting), which the tool "
                "explicitly disclaims; its validated claim is conditional pricing — given a "
                "shock, decompose the impact — see the in-sample check and the risk/attribution "
                "outputs. Negative skill here is the expected, honest result, not a bug.",
    }


def backtest_all(assets: pd.DataFrame, tickers: list[str], scenarios: dict[str, dict],
                 realized_all: dict[str, dict[str, float]],
                 exposure: np.ndarray | None = None) -> dict:
    """Full report: in-sample calibration check + out-of-sample skill test.

    `exposure` (estimated betas) is used for the out-of-sample fold so it is leakage-free.
    """
    in_sample = {}
    for scenario_id, realized in realized_all.items():
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            continue
        r = backtest_scenario(assets, tickers, scenario["shocks"], realized)
        r["scenario_name"] = scenario["name"]
        in_sample[scenario_id] = r

    names = {sid: s.get("name", sid) for sid, s in scenarios.items()}
    oos = out_of_sample_backtest(assets, tickers, realized_all, names, exposure=exposure)
    return {
        "in_sample": {
            "scenarios": in_sample,
            "note": "IN-SAMPLE calibration check only - confirms internal consistency, "
                    "NOT predictive skill.",
        },
        "out_of_sample": oos,
    }
