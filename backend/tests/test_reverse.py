import numpy as np
import pytest

from analytics.reverse import reverse_stress


def _setup():
    # 3 assets, 2 factors.
    B = np.array([
        [1.0, 0.0],     # pure equity
        [0.0, -7.5],    # pure rates (duration)
        [0.5, -4.0],    # mixed
    ])
    factor_cov = np.array([
        [0.16 ** 2 / 52, 0.0],
        [0.0, (0.010 ** 2) / 52],
    ])
    factor_names = ["Equity", "Rates"]
    return B, factor_cov, factor_names


def test_reverse_stress_hits_target_loss():
    B, cov, names = _setup()
    w = np.array([0.5, 0.3, 0.2])
    res = reverse_stress(w, B, cov, target_loss=0.20, factor_names=names)
    # Implied loss must equal the requested target.
    assert res.implied_loss == pytest.approx(0.20, abs=1e-9)


def test_reverse_stress_solution_is_minimum_norm():
    # The closed-form solution s* = -L * Sigma g / (g' Sigma g) must satisfy the constraint
    # g's* = -L, and any other feasible s must have >= Mahalanobis distance.
    B, cov, names = _setup()
    w = np.array([0.4, 0.4, 0.2])
    L = 0.15
    res = reverse_stress(w, B, cov, target_loss=L, factor_names=names)

    g = B.T @ w
    s_star = np.array([res.shocks[n] for n in names])
    assert g @ s_star == pytest.approx(-L, abs=1e-9)

    inv = np.linalg.inv(cov)
    d_star = s_star @ inv @ s_star
    # Perturb along the null space of the constraint; distance must not decrease.
    # Null direction v with g'v = 0:
    v = np.array([g[1], -g[0]])
    for eps in (-0.01, 0.01):
        s_alt = s_star + eps * v
        assert s_alt @ inv @ s_alt >= d_star - 1e-12


def test_mahalanobis_distance_positive():
    B, cov, names = _setup()
    w = np.array([0.5, 0.3, 0.2])
    res = reverse_stress(w, B, cov, target_loss=0.20, factor_names=names)
    assert res.mahalanobis_distance > 0
