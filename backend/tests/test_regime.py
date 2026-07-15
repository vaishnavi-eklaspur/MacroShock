import numpy as np

from analytics import regime


def _returns_with_crises(seed=5):
    rng = np.random.default_rng(seed)
    calm = rng.standard_normal((200, 4)) * 0.01
    crisis = rng.standard_normal((20, 4)) * 0.05      # high-vol weeks
    X = np.vstack([calm, crisis])
    rng.shuffle(X)
    return X


def test_crisis_mask_flags_high_stress_weeks():
    X = _returns_with_crises()
    mask = regime.crisis_mask(X, quantile=0.85)
    assert mask.dtype == bool
    assert mask.sum() > 0
    assert mask.sum() < len(X)                          # not everything is a crisis


def test_conditional_covariance_shape_and_psd():
    X = _returns_with_crises()
    mask = regime.crisis_mask(X)
    cov = regime.conditional_covariance(X, mask)
    assert cov.shape == (4, 4)
    assert np.all(np.linalg.eigvalsh(cov) > -1e-10)


def test_regime_summary_reports_amplification():
    X = _returns_with_crises()
    summary = regime.regime_summary(X)
    assert set(summary) >= {"n_weeks", "n_crisis_weeks", "crisis_fraction",
                            "avg_calm_vol", "avg_crisis_vol", "vol_amplification"}
    assert summary["vol_amplification"] > 1.0           # crisis weeks are more volatile
