"""Core portfolio statistics: return, covariance, volatility, VaR, CVaR.

All formulas are specified in docs/METHODOLOGY.md sections 2-4.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

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
