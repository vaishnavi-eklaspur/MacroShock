import pandas as pd
import pytest

from analytics import backtest as bt


def _assets():
    # Full column set the exposure/pricing functions expect.
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


def _scenario():
    return {"shocks": {"Equity": -0.34, "Rates": -0.012, "Credit": 0.02,
                       "Commodity": -0.40, "Liquidity": -0.25, "FX": 0.08}}


def test_backtest_scenario_computes_errors():
    assets, tickers = _assets()
    realized = {"SPY": -0.34, "IEF": 0.06, "LQD": -0.12, "GLD": -0.02, "DBC": -0.38}
    r = bt.backtest_scenario(assets, tickers, _scenario()["shocks"], realized)
    assert len(r["per_asset"]) == 5
    assert r["mae"] >= 0.0
    assert r["rmse"] >= r["mae"] - 1e-12                 # RMSE >= MAE always
    # each per-asset row exposes predicted/realized/error
    for row in r["per_asset"]:
        assert row["error"] == pytest.approx(row["predicted"] - row["realized"])


def test_backtest_all_aggregates():
    assets, tickers = _assets()
    scenarios = {"COVID_2020": {**_scenario(), "name": "2020 COVID"}}
    realized_all = {"COVID_2020": {"SPY": -0.34, "IEF": 0.06, "LQD": -0.12,
                                   "GLD": -0.02, "DBC": -0.38}}
    out = bt.backtest_all(assets, tickers, scenarios, realized_all)
    assert "COVID_2020" in out["scenarios"]
    assert out["overall_mae"] >= 0.0
    assert out["overall_rmse"] >= 0.0
