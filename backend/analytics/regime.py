"""Regime detection and regime-conditional covariance.

Correlations and volatilities are not constant - they spike in crises. A single
full-sample covariance therefore understates crisis risk and hides the way risk
attribution shifts under stress. Here we label high-stress weeks empirically and estimate a
covariance conditional on that crisis regime.

Detection is deliberately simple and transparent (a volatility-norm threshold), not a
black box: weekly cross-asset stress = L2 norm of that week's standardized returns; weeks
above a high quantile are the crisis regime.
"""
from __future__ import annotations

import numpy as np

from .portfolio import ledoit_wolf_covariance


def crisis_mask(returns: np.ndarray, quantile: float = 0.85) -> np.ndarray:
    """Boolean mask of crisis weeks: those whose standardized-return norm exceeds `quantile`."""
    X = np.asarray(returns, dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd[sd == 0] = 1.0
    z = (X - mu) / sd
    stress = np.sqrt((z ** 2).sum(axis=1))          # per-week stress magnitude
    threshold = np.quantile(stress, quantile)
    return stress >= threshold


def conditional_covariance(returns: np.ndarray, mask: np.ndarray,
                           shrink: bool = True) -> np.ndarray:
    """Covariance estimated on the subset of weeks selected by `mask`.

    Uses Ledoit-Wolf shrinkage (the crisis subsample is small, so estimation error is high).
    """
    X = np.asarray(returns, dtype=float)[mask]
    if X.shape[0] < X.shape[1] + 2:
        # too few crisis obs to estimate a full covariance; fall back to full-sample shrunk cov
        X = np.asarray(returns, dtype=float)
    if shrink:
        cov, _ = ledoit_wolf_covariance(X)
        return cov
    return np.cov(X, rowvar=False, ddof=1)


def regime_summary(returns: np.ndarray, quantile: float = 0.85) -> dict:
    """Descriptive stats: how many crisis weeks, and how much vol amplifies in them."""
    X = np.asarray(returns, dtype=float)
    mask = crisis_mask(X, quantile)
    calm_vol = X[~mask].std(axis=0, ddof=1).mean() if (~mask).sum() > 1 else 0.0
    crisis_vol = X[mask].std(axis=0, ddof=1).mean() if mask.sum() > 1 else 0.0
    return {
        "n_weeks": int(X.shape[0]),
        "n_crisis_weeks": int(mask.sum()),
        "crisis_fraction": float(mask.mean()),
        "avg_calm_vol": float(calm_vol),
        "avg_crisis_vol": float(crisis_vol),
        "vol_amplification": float(crisis_vol / calm_vol) if calm_vol > 0 else 0.0,
    }
