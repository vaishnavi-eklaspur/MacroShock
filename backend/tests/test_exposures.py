"""Estimated exposures: honest R² and beta recovery (kills the circular-factor critique)."""
import numpy as np

from analytics import factors as fac


def test_estimate_exposures_recovers_betas_with_honest_r2():
    rng = np.random.default_rng(0)
    n_factors = len(fac.FACTOR_ORDER)
    T, n = 1000, 6
    B_true = rng.standard_normal((n, n_factors))
    F = rng.standard_normal((T, n_factors)) * 0.01          # independent factor series
    idio = rng.standard_normal((T, n)) * 0.005              # real idiosyncratic risk
    A = F @ B_true.T + idio

    B_hat, r2 = fac.estimate_exposures(A, F)
    assert B_hat.shape == (n, n_factors)
    assert np.allclose(B_hat, B_true, atol=0.1)              # betas recovered (within sampling error)
    # With genuine idiosyncratic noise, R² is well below 1.0 — the whole point: the factors
    # are independent, not a projection of the assets.
    assert (r2 < 0.99).all()
    assert (r2 > 0.3).all()


def test_projection_would_be_tautological():
    # Sanity check on the critique itself: if factors ARE derived from the assets by pinv,
    # regressing back gives ~perfect R² — which is exactly what we now avoid.
    rng = np.random.default_rng(1)
    A = rng.standard_normal((300, 6)) * 0.01
    B = rng.standard_normal((6, len(fac.FACTOR_ORDER)))
    F_circular = A @ np.linalg.pinv(B).T                     # the old, circular derivation
    _, r2 = fac.estimate_exposures(A, F_circular)
    assert (r2 > 0.999).all()                                # tautological — what we fixed
