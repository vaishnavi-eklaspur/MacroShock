import numpy as np

from analytics import regime


def _returns_with_crises(seed=5):
    rng = np.random.default_rng(seed)
    calm = rng.standard_normal((260, 4)) * 0.01
    crisis = rng.standard_normal((26, 4)) * 0.06      # high-vol weeks
    X = np.vstack([calm, crisis])
    rng.shuffle(X)
    return X


def test_chi_square_flags_few_on_calm_data():
    # Pure calm normal data: a principled detector must NOT flag ~15% as crisis.
    rng = np.random.default_rng(11)
    calm = rng.standard_normal((500, 4)) * 0.01
    mask = regime.crisis_mask(calm, p=0.99)
    assert mask.mean() < 0.10        # far below a naive top-15% rule


def test_crisis_mask_flags_real_crises():
    X = _returns_with_crises()
    mask = regime.crisis_mask(X, p=0.99)
    assert mask.dtype == bool
    assert 0 < mask.sum() < len(X)


def test_conditional_covariance_returns_cov_and_flag():
    X = _returns_with_crises()
    mask = regime.crisis_mask(X)
    cov, fallback = regime.conditional_covariance(X, mask)
    assert cov.shape == (4, 4)
    assert np.all(np.linalg.eigvalsh(cov) > -1e-8)
    assert isinstance(fallback, bool)


def test_regime_summary_reports_expected_false_positive_rate():
    X = _returns_with_crises()
    s = regime.regime_summary(X, p=0.99)
    assert s["expected_fraction_if_normal"] == 0.01
    assert s["vol_amplification"] > 1.0
