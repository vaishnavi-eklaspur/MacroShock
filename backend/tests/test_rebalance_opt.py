import numpy as np
import pytest

from analytics.rebalance import optimize_rebalance


@pytest.fixture
def setup():
    tickers = ["A", "B", "C"]
    # C is high-vol; a min-variance solver should trim it.
    cov = np.array([
        [0.040, 0.006, 0.002],
        [0.006, 0.050, 0.004],
        [0.002, 0.004, 0.200],
    ])
    scenario = np.array([-0.10, -0.05, 0.02])   # C actually cushions the scenario
    w0 = np.array([0.4, 0.3, 0.3])
    return w0, tickers, scenario, cov


def test_optimizer_respects_constraints(setup):
    w0, tickers, scenario, cov = setup
    rec = optimize_rebalance(w0, tickers, scenario, cov, per_asset_cap=0.15)
    new = np.array([rec.new_weights[t] for t in tickers])
    assert new.sum() == pytest.approx(1.0, abs=1e-6)          # fully invested
    assert np.all(new >= -1e-9)                                # long-only
    assert np.all(np.abs(new - w0) <= 0.15 + 1e-6)             # per-asset turnover cap


def test_optimizer_does_not_worsen_drawdown(setup):
    w0, tickers, scenario, cov = setup
    rec = optimize_rebalance(w0, tickers, scenario, cov)
    if rec.applied:
        assert rec.new_drawdown >= rec.old_drawdown - 1e-9     # scenario not made worse
        assert rec.new_volatility <= rec.old_volatility + 1e-9  # risk reduced


def test_optimizer_reports_turnover(setup):
    w0, tickers, scenario, cov = setup
    rec = optimize_rebalance(w0, tickers, scenario, cov)
    assert rec.turnover >= 0.0
