import numpy as np
import pytest

from analytics import portfolio as pf
from analytics.risk import risk_contributions


@pytest.fixture
def cov():
    return np.array([
        [0.040, 0.006, 0.002],
        [0.006, 0.090, 0.004],
        [0.002, 0.004, 0.160],
    ])


def test_euler_identity_component_sums_to_volatility(cov):
    w = np.array([0.5, 0.3, 0.2])
    rc = risk_contributions(w, cov)
    assert rc.component.sum() == pytest.approx(rc.portfolio_volatility)
    assert abs(rc.euler_check()) < 1e-12


def test_percentage_contributions_sum_to_one(cov):
    w = np.array([0.5, 0.3, 0.2])
    rc = risk_contributions(w, cov)
    assert rc.percentage.sum() == pytest.approx(1.0)


def test_marginal_matches_definition(cov):
    w = pf.normalize_weights(np.array([0.5, 0.3, 0.2]))
    rc = risk_contributions(w, cov)
    sigma = pf.portfolio_volatility(w, cov)
    expected_marginal = (cov @ w) / sigma
    assert np.allclose(rc.marginal, expected_marginal)


def test_risk_can_exceed_capital_share(cov):
    # A high-vol asset should carry a larger risk share than its capital weight.
    w = np.array([0.6, 0.2, 0.2])
    rc = risk_contributions(w, cov)
    # asset index 2 has the highest variance (0.16)
    assert rc.percentage[2] > w[2]
