import numpy as np
import pandas as pd
import pytest

from analytics import factors as fac


def test_ols_recovers_known_betas():
    rng = np.random.default_rng(42)
    T = 2000
    F = rng.standard_normal((T, 2)) * 0.02
    true_alpha, true_betas = 0.001, np.array([0.8, -1.5])
    y = true_alpha + F @ true_betas + rng.standard_normal(T) * 1e-4

    reg = fac.ols_factor_betas(y, F, ["Equity", "Rates"])
    assert reg.betas["Equity"] == pytest.approx(0.8, abs=1e-2)
    assert reg.betas["Rates"] == pytest.approx(-1.5, abs=1e-2)
    assert reg.r_squared > 0.99


def _assets():
    return pd.DataFrame([
        {"ticker": "SPY", "equity_beta": 1.0, "eff_duration": 0.0, "spread_duration": 0.0,
         "commodity_beta": 0.1, "liquidity_beta": 0.3, "fx_beta": -0.1, "convexity": 0.0},
        {"ticker": "IEF", "equity_beta": -0.05, "eff_duration": 7.5, "spread_duration": 0.0,
         "commodity_beta": 0.0, "liquidity_beta": -0.1, "fx_beta": 0.05, "convexity": 75.0},
        {"ticker": "LQD", "equity_beta": 0.2, "eff_duration": 8.4, "spread_duration": 8.4,
         "commodity_beta": 0.0, "liquidity_beta": 0.8, "fx_beta": -0.05, "convexity": 95.0},
    ])


def test_scenario_bond_pricing_includes_convexity():
    assets = _assets()
    # Rates down 150bps only.
    shocks = {"Equity": 0.0, "Rates": -0.015, "Credit": 0.0, "Commodity": 0.0}
    r = fac.scenario_asset_returns(assets, shocks)
    # IEF: -D*dy + 0.5*C*dy^2 = -7.5*(-0.015) + 0.5*75*0.015^2
    expected_ief = -7.5 * (-0.015) + 0.5 * 75.0 * (-0.015) ** 2
    assert r[1] == pytest.approx(expected_ief)


def test_factor_pnl_sums_to_portfolio_return():
    assets = _assets()
    w = np.array([0.5, 0.3, 0.2])
    shocks = {"Equity": -0.30, "Rates": -0.01, "Credit": 0.02, "Commodity": -0.10,
              "Liquidity": -0.15, "FX": 0.08}
    total = float(w @ fac.scenario_asset_returns(assets, shocks))
    breakdown = fac.factor_pnl_breakdown(assets, w, shocks)
    assert sum(breakdown.values()) == pytest.approx(total)
    assert set(breakdown) == {"Equity", "Rates", "Credit", "Commodity", "Liquidity", "FX"}


def test_exposure_matrix_signs():
    assets = _assets()
    B = fac.exposure_matrix(assets)
    # Rates column = -eff_duration ; Credit column = -spread_duration
    assert B[1, 1] == pytest.approx(-7.5)
    assert B[2, 2] == pytest.approx(-8.4)



def test_vif_detects_collinearity():
    rng = np.random.default_rng(9)
    base = rng.standard_normal(1000)
    f1 = base + rng.standard_normal(1000) * 0.05      # f1, f2 nearly collinear
    f2 = base + rng.standard_normal(1000) * 0.05
    f3 = rng.standard_normal(1000)
    F = np.column_stack([f1, f2, f3])
    vif = fac.variance_inflation_factors(F, ["A", "B", "C"])
    assert vif["A"] > 5 and vif["B"] > 5      # collinear pair inflated
    assert vif["C"] < 2                        # independent factor fine
    assert fac.factor_condition_number(F) > fac.factor_condition_number(
        rng.standard_normal((1000, 3)))


def test_ridge_shrinks_coefficients():
    rng = np.random.default_rng(10)
    F = rng.standard_normal((500, 2)) * 0.02
    y = 0.8 * F[:, 0] - 1.2 * F[:, 1] + rng.standard_normal(500) * 1e-3
    ols = fac.ols_factor_betas(y, F, ["X", "Y"], ridge_lambda=0.0)
    ridge = fac.ols_factor_betas(y, F, ["X", "Y"], ridge_lambda=10.0)
    assert abs(ridge.betas["X"]) <= abs(ols.betas["X"]) + 1e-9
    assert ridge.ridge_lambda == 10.0
