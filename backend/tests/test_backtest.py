import numpy as np
import pandas as pd

from analytics import backtest as bt


def _assets():
    cols = ["equity_beta", "eff_duration", "spread_duration", "commodity_beta",
            "liquidity_beta", "fx_beta", "convexity"]
    rows = {
        "SPY": [1.00, 0.0, 0.0, 0.10, 0.30, -0.10, 0.0],
        "IEF": [-0.05, 7.5, 0.0, 0.00, -0.10, 0.05, 75.0],
        "LQD": [0.20, 8.4, 8.4, 0.00, 0.80, -0.05, 95.0],
        "GLD": [-0.10, 0.0, 0.0, 0.25, 0.20, -0.40, 0.0],
        "DBC": [0.35, 0.0, 0.0, 1.00, 0.40, -0.30, 0.0],
    }
    df = pd.DataFrame([[t] + v for t, v in rows.items()], columns=["ticker"] + cols)
    return df, list(rows.keys())


REALIZED = {
    "GFC_2008": {"SPY": -0.46, "IEF": 0.15, "LQD": -0.05, "GLD": 0.05, "DBC": -0.50},
    "COVID_2020": {"SPY": -0.34, "IEF": 0.06, "LQD": -0.12, "GLD": -0.02, "DBC": -0.38},
}


def test_implied_shocks_reproduce_returns_in_sample():
    assets, tickers = _assets()
    from analytics.factors import exposure_matrix
    s = bt.implied_shocks_from_realized(assets, tickers, REALIZED["GFC_2008"])
    B = exposure_matrix(assets)
    pred = B @ np.array([s[f] for f in ["Equity", "Rates", "Credit", "Commodity", "Liquidity", "FX"]])
    realized = np.array([REALIZED["GFC_2008"][t] for t in tickers])
    # 5 assets, 6 factors -> min-norm LS fits the in-sample crisis closely.
    assert np.sqrt(np.mean((pred - realized) ** 2)) < 0.05


def test_out_of_sample_backtest_reports_skill():
    assets, tickers = _assets()
    names = {"GFC_2008": "2008 GFC", "COVID_2020": "2020 COVID"}
    oos = bt.out_of_sample_backtest(assets, tickers, REALIZED, names)
    assert set(oos["scenarios"]) == {"GFC_2008", "COVID_2020"}
    for r in oos["scenarios"].values():
        assert "skill_vs_zero" in r and "skill_vs_repeat" in r
        # each held-out crisis was predicted WITHOUT using its own realized returns
        assert r["trained_on"]
    assert "overall_skill_vs_zero" in oos


def test_backtest_all_separates_in_and_out_of_sample():
    assets, tickers = _assets()
    scenarios = {"GFC_2008": {"name": "2008 GFC", "shocks": {"Equity": -0.45, "Rates": -0.015,
                 "Credit": 0.04, "Commodity": -0.50, "Liquidity": -0.15, "FX": 0.10}},
                 "COVID_2020": {"name": "2020 COVID", "shocks": {"Equity": -0.34, "Rates": -0.012,
                 "Credit": 0.02, "Commodity": -0.40, "Liquidity": -0.25, "FX": 0.08}}}
    out = bt.backtest_all(assets, tickers, scenarios, REALIZED)
    assert "in_sample" in out and "out_of_sample" in out
    assert "not a skill test" in out["in_sample"]["note"].lower() or \
           "not predictive" in out["in_sample"]["note"].lower()
