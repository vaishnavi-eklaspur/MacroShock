import numpy as np
import pytest

from analytics.reverse import reverse_stress


def _setup():
    # 2 factors named so DEFAULT_BOUNDS applies (Equity, Rates).
    B = np.array([
        [1.0, 0.0],
        [0.0, -7.5],
        [0.5, -4.0],
    ])
    factor_cov = np.array([
        [0.16 ** 2 / 52, 0.0],
        [0.0, (0.010 ** 2) / 52],
    ])
    return B, factor_cov, ["Equity", "Rates"]


def test_reverse_stress_hits_target_loss():
    B, cov, names = _setup()
    w = np.array([0.5, 0.3, 0.2])
    res = reverse_stress(w, B, cov, target_loss=0.20, factor_names=names)
    # Primary (constrained or fallback) must produce the requested loss.
    assert res.implied_loss == pytest.approx(0.20, abs=1e-6)


def test_unconstrained_is_minimum_norm():
    B, cov, names = _setup()
    w = np.array([0.4, 0.4, 0.2])
    L = 0.15
    res = reverse_stress(w, B, cov, target_loss=L, factor_names=names)

    g = B.T @ w
    s_unc = np.array([res.unconstrained_shocks[n] for n in names])
    assert g @ s_unc == pytest.approx(-L, abs=1e-9)

    inv = np.linalg.inv(cov)
    d_star = s_unc @ inv @ s_unc
    v = np.array([g[1], -g[0]])  # null direction of the constraint
    for eps in (-0.01, 0.01):
        s_alt = s_unc + eps * v
        assert s_alt @ inv @ s_alt >= d_star - 1e-12


def test_alternatives_ranked_by_plausibility():
    B, cov, names = _setup()
    w = np.array([0.5, 0.3, 0.2])
    res = reverse_stress(w, B, cov, target_loss=0.20, factor_names=names, top_k=2)
    dists = [a["mahalanobis_distance"] for a in res.alternatives]
    assert dists == sorted(dists)                 # ascending plausibility
    for a in res.alternatives:                    # each single-factor path hits the loss
        s = np.array([a["shocks"][n] for n in names])
        assert (B.T @ w) @ s == pytest.approx(-0.20, abs=1e-9)


def test_mahalanobis_distance_positive():
    B, cov, names = _setup()
    w = np.array([0.5, 0.3, 0.2])
    res = reverse_stress(w, B, cov, target_loss=0.20, factor_names=names)
    assert res.mahalanobis_distance > 0
