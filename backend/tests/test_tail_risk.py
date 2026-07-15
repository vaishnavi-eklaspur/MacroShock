import numpy as np
import pytest

from analytics import portfolio as pf


@pytest.fixture
def fat_tailed_series():
    rng = np.random.default_rng(7)
    # Student-t sample (fat tails, slight negative skew via a shift on the tail).
    x = rng.standard_t(4, size=5000) * 0.01
    x[x < np.quantile(x, 0.02)] *= 1.3  # accentuate the left tail
    return x


def test_historical_cvar_ge_var(fat_tailed_series):
    var = pf.historical_var(fat_tailed_series, 0.95)
    cvar = pf.historical_cvar(fat_tailed_series, 0.95)
    assert cvar >= var


def test_student_t_var_exceeds_gaussian_deep_tail():
    sigma = 0.02
    assert pf.student_t_var(sigma, 0.99, dof=5) > pf.parametric_var(sigma, 0.99)


def test_cornish_fisher_recovers_gaussian_on_normal_data():
    rng = np.random.default_rng(1)
    normal = rng.standard_normal(20000) * 0.01
    cf = pf.cornish_fisher_var(normal, 0.95)
    gauss = pf.parametric_var(normal.std(ddof=1), 0.95, mu=normal.mean(), include_drift=True)
    assert cf == pytest.approx(gauss, abs=3e-3)


def test_sample_moments_detects_fat_tails(fat_tailed_series):
    m = pf.sample_moments(fat_tailed_series)
    assert m["excess_kurtosis"] > 1.0  # clearly leptokurtic


def test_ledoit_wolf_is_valid_covariance():
    rng = np.random.default_rng(3)
    X = rng.standard_normal((120, 5)) * 0.02
    cov, shrink = pf.ledoit_wolf_covariance(X)
    assert cov.shape == (5, 5)
    assert 0.0 <= shrink <= 1.0
    assert np.allclose(cov, cov.T)                      # symmetric
    assert np.all(np.linalg.eigvalsh(cov) > -1e-10)     # PSD



def test_jarque_bera_rejects_fat_tails(fat_tailed_series):
    jb = pf.jarque_bera(fat_tailed_series)
    assert jb["normal_rejected"] is True
    assert jb["p_value"] < 0.05


def test_jarque_bera_does_not_reject_normal():
    rng = np.random.default_rng(2)
    normal = rng.standard_normal(5000) * 0.01
    jb = pf.jarque_bera(normal)
    assert jb["p_value"] > 0.01


def test_fit_student_t_dof_low_for_fat_tails(fat_tailed_series):
    dof = pf.fit_student_t_dof(fat_tailed_series)
    assert 2.1 <= dof <= 100.0
    assert dof < 15.0                       # genuinely fat-tailed => low dof


def test_cornish_fisher_valid_on_near_normal():
    rng = np.random.default_rng(4)
    normal = rng.standard_normal(10000) * 0.01
    assert pf.cornish_fisher_valid(normal) is True


def test_constant_correlation_shrinkage_valid():
    rng = np.random.default_rng(6)
    X = rng.standard_normal((150, 5)) * 0.02
    cov, delta = pf.ledoit_wolf_constant_correlation(X)
    assert cov.shape == (5, 5)
    assert 0.0 <= delta <= 1.0
    assert np.allclose(cov, cov.T)
    assert np.all(np.linalg.eigvalsh(cov) > -1e-8)
