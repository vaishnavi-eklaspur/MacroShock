"""Core portfolio statistics: return, covariance, volatility, VaR, CVaR.

All formulas are specified in docs/METHODOLOGY.md sections 2-4.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import jarque_bera as _jarque_bera
from scipy.stats import kurtosis, norm, skew
from scipy.stats import t as student_t

WEEKS_PER_YEAR = 52


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    """Return weights scaled to sum to 1.0 (guards against tiny UI rounding drift)."""
    w = np.asarray(weights, dtype=float)
    total = w.sum()
    if not np.isfinite(total) or total == 0:
        raise ValueError("Weights must sum to a non-zero, finite value.")
    return w / total


def covariance_matrix(returns: np.ndarray) -> np.ndarray:
    """Sample covariance (ddof=1) of a T x n periodic-return matrix -> n x n."""
    returns = np.asarray(returns, dtype=float)
    return np.cov(returns, rowvar=False, ddof=1)


def portfolio_return(weights: np.ndarray, asset_returns: np.ndarray) -> float:
    """Single-period portfolio return R_p = wᵀr."""
    return float(np.dot(normalize_weights(weights), np.asarray(asset_returns, dtype=float)))


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """Portfolio volatility sigma_p = sqrt(wᵀ Σ w) (periodic)."""
    w = normalize_weights(weights)
    var = float(w @ np.asarray(cov, dtype=float) @ w)
    return float(np.sqrt(max(var, 0.0)))


def annualize_volatility(sigma_periodic: float, periods_per_year: int = WEEKS_PER_YEAR) -> float:
    """sigma_annual = sigma_periodic * sqrt(P)."""
    return float(sigma_periodic * np.sqrt(periods_per_year))


def parametric_var(sigma_p: float, alpha: float = 0.95, mu: float = 0.0,
                   include_drift: bool = False) -> float:
    """Gaussian VaR as a positive loss: VaR = z_a * sigma_p - mu (mu applied only if include_drift)."""
    z = float(norm.ppf(alpha))
    drift = mu if include_drift else 0.0
    return float(z * sigma_p - drift)


def parametric_cvar(sigma_p: float, alpha: float = 0.95, mu: float = 0.0,
                    include_drift: bool = False) -> float:
    """Gaussian Expected Shortfall (CVaR): sigma_p * phi(z_a)/(1-a) - mu. Always >= VaR."""
    z = float(norm.ppf(alpha))
    drift = mu if include_drift else 0.0
    return float(sigma_p * float(norm.pdf(z)) / (1.0 - alpha) - drift)


def historical_var(portfolio_returns: np.ndarray, alpha: float = 0.95) -> float:
    """Empirical VaR: negative of the (1-alpha) quantile of realized portfolio returns."""
    r = np.asarray(portfolio_returns, dtype=float)
    return float(-np.quantile(r, 1.0 - alpha))


def cumulative_return(period_returns: np.ndarray) -> float:
    """Compounded cumulative return over a sequence of periodic returns."""
    r = np.asarray(period_returns, dtype=float)
    return float(np.prod(1.0 + r) - 1.0)


# --------------------------------------------------------------------- fat-tailed risk
def historical_cvar(portfolio_returns: np.ndarray, alpha: float = 0.95) -> float:
    """Empirical Expected Shortfall: mean loss in the worst (1-alpha) tail."""
    r = np.asarray(portfolio_returns, dtype=float)
    q = np.quantile(r, 1.0 - alpha)
    tail = r[r <= q]
    return float(-tail.mean()) if tail.size else float(-q)


def sample_moments(portfolio_returns: np.ndarray) -> dict[str, float]:
    """Mean, std, skewness and EXCESS kurtosis of a return series."""
    r = np.asarray(portfolio_returns, dtype=float)
    return {
        "mean": float(r.mean()),
        "std": float(r.std(ddof=1)),
        "skew": float(skew(r, bias=False)),
        "excess_kurtosis": float(kurtosis(r, fisher=True, bias=False)),
    }


def cornish_fisher_var(portfolio_returns: np.ndarray, alpha: float = 0.95) -> float:
    """Modified (Cornish-Fisher) VaR that corrects the Gaussian quantile for skew/kurtosis.

    The CF expansion adjusts the standard-normal quantile z (lower tail) using the sample
    skewness S and excess kurtosis K:

        z_cf = z + (z²-1)/6·S + (z³-3z)/24·K − (2z³-5z)/36·S²
        VaR  = −(μ + σ·z_cf)      (positive loss)

    For fat-tailed data this exceeds Gaussian VaR - which is the point.
    """
    m = sample_moments(portfolio_returns)
    z = float(norm.ppf(1.0 - alpha))  # lower-tail (negative)
    S, K = m["skew"], m["excess_kurtosis"]
    z_cf = (z + (z**2 - 1) / 6 * S + (z**3 - 3 * z) / 24 * K - (2 * z**3 - 5 * z) / 36 * S**2)
    return float(-(m["mean"] + m["std"] * z_cf))


def student_t_var(sigma_p: float, alpha: float = 0.95, dof: float = 5.0,
                  mu: float = 0.0, include_drift: bool = False) -> float:
    """Parametric VaR under a Student-t with `dof` degrees of freedom, scaled to vol sigma_p.

    The t-quantile is rescaled by sqrt((dof-2)/dof) so the distribution's std equals sigma_p.
    """
    drift = mu if include_drift else 0.0
    dof = max(dof, 2.05)
    q = float(student_t.ppf(1.0 - alpha, dof)) * np.sqrt((dof - 2.0) / dof)
    return float(-(drift + sigma_p * q))


def fit_student_t_dof(portfolio_returns: np.ndarray) -> float:
    """MLE-fit the Student-t degrees of freedom to the return series.

    Reporting the *fitted* dof (rather than a hard-coded guess) lets the tail model be
    driven by the data. Clipped to a sensible range for numerical stability.
    """
    r = np.asarray(portfolio_returns, dtype=float)
    try:
        dof, _loc, _scale = student_t.fit(r)
        if not np.isfinite(dof):
            return 30.0
        return float(min(max(dof, 2.1), 100.0))
    except Exception:
        return 30.0


def jarque_bera(portfolio_returns: np.ndarray) -> dict[str, float]:
    """Jarque-Bera test of normality: statistic + p-value.

    A small p-value rejects normality (fat tails / skew) - the statistical evidence that
    Gaussian VaR is inadequate, rather than an asserted claim.
    """
    r = np.asarray(portfolio_returns, dtype=float)
    stat, p = _jarque_bera(r)
    return {"statistic": float(stat), "p_value": float(p), "normal_rejected": bool(p < 0.05)}


def cornish_fisher_valid(portfolio_returns: np.ndarray) -> bool:
    """Whether the Cornish-Fisher quantile map is monotone (its validity domain).

    The CF expansion is only a valid quantile transform where dz_cf/dz > 0 across the tail.
    Outside that region the modified VaR is unreliable; we flag it so the UI can fall back
    to historical VaR.
    """
    m = sample_moments(portfolio_returns)
    S, K = m["skew"], m["excess_kurtosis"]
    zs = np.linspace(-3.5, -0.3, 60)
    deriv = 1 + (2 * zs) / 6 * S + (3 * zs**2 - 3) / 24 * K - (6 * zs**2 - 5) / 36 * S**2
    return bool(np.all(deriv > 0))


# --------------------------------------------------------------------- robust covariance
def ledoit_wolf_covariance(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf shrinkage of the sample covariance toward a scaled-identity target.

    Returns (Sigma_shrunk, shrinkage_intensity). Shrinkage reduces the estimation error
    that plagues sample covariance (and therefore MCTR) when T is not >> n. Target is
    F = m·I with m = average sample variance; optimal intensity per Ledoit & Wolf (2004).
    """
    X = np.asarray(returns, dtype=float)
    T, n = X.shape
    Xc = X - X.mean(axis=0)
    S = (Xc.T @ Xc) / T                      # MLE sample covariance
    m = np.trace(S) / n
    F = m * np.eye(n)
    d2 = float(np.sum((S - F) ** 2))         # ||S - F||_F^2
    # pi: sum over t of ||x_t x_tᵀ - S||_F^2 / T
    b2_bar = 0.0
    for t in range(T):
        xt = Xc[t][:, None]
        b2_bar += float(np.sum((xt @ xt.T - S) ** 2))
    b2_bar /= T**2
    shrink = 0.0 if d2 == 0 else max(0.0, min(1.0, b2_bar / d2))
    sigma = shrink * F + (1.0 - shrink) * S
    # rescale from /T (MLE) to /(T-1) (unbiased) for consistency with covariance_matrix
    sigma *= T / (T - 1)
    return sigma, float(shrink)


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2003) shrinkage toward the CONSTANT-CORRELATION target.

    The standard choice for asset-return covariance: the target `F` keeps each asset's own
    variance and sets every pairwise correlation to the sample average correlation `r_bar`.
    This preserves the fact that assets are correlated (unlike an identity target that shrinks
    correlations to zero), which matters for a risk tool. Optimal intensity per L&W (2003).

    Returns (Sigma_shrunk, shrinkage_intensity).
    """
    X = np.asarray(returns, dtype=float)
    T, n = X.shape
    Xc = X - X.mean(axis=0)
    S = (Xc.T @ Xc) / T
    var = np.diag(S).copy()
    std = np.sqrt(var)
    outer_std = np.outer(std, std)
    corr = S / outer_std
    # average off-diagonal correlation
    r_bar = (corr.sum() - n) / (n * (n - 1)) if n > 1 else 0.0

    # constant-correlation target
    F = r_bar * outer_std
    np.fill_diagonal(F, var)

    # pi: asymptotic variances of sample covariance entries
    pi_mat = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            pi_mat[i, j] = np.mean((Xc[:, i] * Xc[:, j] - S[i, j]) ** 2)
    pi_hat = float(pi_mat.sum())

    # rho: asymptotic covariances between target and sample estimators
    rho_diag = float(np.trace(pi_mat))
    rho_off = 0.0
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            theta_ii = np.mean((Xc[:, i] ** 2 - S[i, i]) * (Xc[:, i] * Xc[:, j] - S[i, j]))
            theta_jj = np.mean((Xc[:, j] ** 2 - S[j, j]) * (Xc[:, i] * Xc[:, j] - S[i, j]))
            rho_off += (r_bar / 2.0) * (np.sqrt(var[j] / var[i]) * theta_ii
                                        + np.sqrt(var[i] / var[j]) * theta_jj)
    rho_hat = rho_diag + rho_off

    gamma_hat = float(np.sum((F - S) ** 2))
    kappa = (pi_hat - rho_hat) / gamma_hat if gamma_hat > 0 else 0.0
    delta = max(0.0, min(1.0, kappa / T))

    sigma = delta * F + (1.0 - delta) * S
    sigma *= T / (T - 1)                       # unbiased scaling
    sigma = (sigma + sigma.T) / 2.0            # enforce symmetry
    return sigma, float(delta)
