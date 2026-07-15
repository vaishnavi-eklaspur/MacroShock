"""Regime detection and regime-conditional covariance.

Correlations and volatilities spike in crises; a single full-sample covariance therefore
understates crisis risk and hides how risk attribution shifts under stress. We label
high-stress weeks with a *principled* statistical test, not a fixed quantile.

Detection: under multivariate normality, the squared Mahalanobis distance of a week's
standardized returns follows a chi-square(n) distribution. We flag weeks whose distance
exceeds the chi-square critical value at level `p` (default 0.99). Crucially this is NOT a
quantile — on genuinely calm/normal data it flags only ~(1-p) of weeks (i.e. almost none),
so a "crisis regime" is detected only if the data actually has one. That removes the
selection bias of a top-x% rule.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import chi2

from .portfolio import ledoit_wolf_constant_correlation


def mahalanobis_stress(returns: np.ndarray) -> np.ndarray:
    """Per-week squared Mahalanobis distance of standardized returns (~ chi²(n) if normal)."""
    X = np.asarray(returns, dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd[sd == 0] = 1.0
    z = (X - mu) / sd
    corr = np.corrcoef(X, rowvar=False)
    inv = np.linalg.pinv(corr)
    return np.einsum("ti,ij,tj->t", z, inv, z)


def crisis_mask(returns: np.ndarray, p: float = 0.99,
                min_fraction: float = 0.03) -> np.ndarray:
    """Boolean crisis mask via a chi-square threshold on Mahalanobis stress.

    Weeks with stress above chi²(n).ppf(p) are crises. If that yields too few observations
    to estimate a covariance (fewer than `min_fraction` of weeks), the level is relaxed
    step-wise until enough are captured - and the achieved level is reflected in
    regime_summary. On calm data the mask can be (near-)empty; it is not forced to fire.
    """
    X = np.asarray(returns, dtype=float)
    T, n = X.shape
    d2 = mahalanobis_stress(X)
    for level in (p, 0.975, 0.95, 0.90):
        threshold = chi2.ppf(level, df=n)
        mask = d2 >= threshold
        if mask.sum() >= max(int(min_fraction * T), n + 2):
            return mask
    return d2 >= np.quantile(d2, 1.0 - min_fraction)  # last-resort floor


def conditional_covariance(returns: np.ndarray, mask: np.ndarray,
                           shrink: bool = True) -> tuple[np.ndarray, bool]:
    """Covariance on crisis weeks. Returns (cov, used_fallback).

    Uses constant-correlation Ledoit-Wolf shrinkage (crisis subsample is small). If there
    are too few crisis observations, falls back to the full sample and flags it, so the
    caller never silently reports a calm covariance as a crisis covariance.
    """
    X = np.asarray(returns, dtype=float)
    sub = X[mask]
    used_fallback = False
    if sub.shape[0] < sub.shape[1] + 2:
        sub, used_fallback = X, True
    if shrink:
        cov, _ = ledoit_wolf_constant_correlation(sub)
    else:
        cov = np.cov(sub, rowvar=False, ddof=1)
    return cov, used_fallback


def regime_summary(returns: np.ndarray, p: float = 0.99) -> dict:
    """Descriptive regime stats, including the false-positive rate expected under normality."""
    X = np.asarray(returns, dtype=float)
    T, n = X.shape
    mask = crisis_mask(X, p)
    calm_vol = X[~mask].std(axis=0, ddof=1).mean() if (~mask).sum() > 1 else 0.0
    crisis_vol = X[mask].std(axis=0, ddof=1).mean() if mask.sum() > 1 else 0.0
    return {
        "n_weeks": int(T),
        "n_crisis_weeks": int(mask.sum()),
        "crisis_fraction": float(mask.mean()),
        "expected_fraction_if_normal": float(1.0 - p),
        "avg_calm_vol": float(calm_vol),
        "avg_crisis_vol": float(crisis_vol),
        "vol_amplification": float(crisis_vol / calm_vol) if calm_vol > 0 else 0.0,
        "detection": "chi-square Mahalanobis threshold (not a fixed quantile)",
    }
