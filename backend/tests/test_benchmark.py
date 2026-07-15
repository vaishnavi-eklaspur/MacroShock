"""Benchmark-relative analytics: tracking error, active-risk Euler identity, zero-active case."""
import numpy as np

from analytics import benchmark as bm
from analytics.factors import FACTOR_ORDER


def _setup(n=5):
    rng = np.random.default_rng(0)
    X = rng.standard_normal((300, n)) * 0.02
    cov = np.cov(X, rowvar=False)
    scov = cov * 2.0
    exposure = rng.standard_normal((n, len(FACTOR_ORDER)))
    return cov, scov, exposure, [f"A{i}" for i in range(n)]


def test_active_pctr_sums_to_one():
    cov, scov, exp, tk = _setup()
    w = np.array([0.4, 0.3, 0.1, 0.1, 0.1])
    wb = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    rep = bm.active_analysis(w, wb, cov, scov, exp, FACTOR_ORDER, tk)
    assert abs(sum(rep["active_risk_pctr_calm"].values()) - 1.0) < 1e-9
    assert rep["tracking_error_annual_calm"] > 0
    assert 0 <= rep["active_share"] <= 1


def test_zero_active_has_zero_tracking_error():
    cov, scov, exp, tk = _setup()
    w = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    rep = bm.active_analysis(w, w, cov, scov, exp, FACTOR_ORDER, tk)   # portfolio == benchmark
    assert rep["tracking_error_annual_calm"] == 0.0
    assert rep["active_share"] == 0.0
    assert all(abs(v) < 1e-12 for v in rep["factor_tilts"].values())
