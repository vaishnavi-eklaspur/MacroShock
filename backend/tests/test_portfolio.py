import numpy as np
import pytest
from scipy.stats import norm

from analytics import portfolio as pf


def test_portfolio_return_is_weighted_sum():
    w = np.array([0.5, 0.5])
    r = np.array([0.10, -0.02])
    assert pf.portfolio_return(w, r) == pytest.approx(0.04)


def test_normalize_weights_sums_to_one():
    w = pf.normalize_weights(np.array([40.0, 20.0, 20.0, 10.0, 10.0]))
    assert w.sum() == pytest.approx(1.0)
    assert w[0] == pytest.approx(0.40)


def test_volatility_matches_closed_form():
    # Two assets, known covariance.
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    w = np.array([0.6, 0.4])
    expected = np.sqrt(w @ cov @ w)
    assert pf.portfolio_volatility(w, cov) == pytest.approx(expected)


def test_annualization():
    assert pf.annualize_volatility(0.02, 52) == pytest.approx(0.02 * np.sqrt(52))


def test_parametric_var_uses_normal_quantile():
    sigma = 0.03
    assert pf.parametric_var(sigma, 0.95) == pytest.approx(norm.ppf(0.95) * sigma)


def test_cvar_greater_than_var():
    sigma = 0.03
    assert pf.parametric_cvar(sigma, 0.95) > pf.parametric_var(sigma, 0.95)


def test_var_scales_with_confidence():
    sigma = 0.03
    assert pf.parametric_var(sigma, 0.99) > pf.parametric_var(sigma, 0.95)
