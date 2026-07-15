"""Risk decomposition: Marginal / Component / Percentage Contribution to Risk.

Euler allocation of portfolio volatility across holdings.
See docs/METHODOLOGY.md section 6.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .portfolio import normalize_weights


@dataclass
class RiskContribution:
    portfolio_volatility: float          # sigma_p (periodic)
    marginal: np.ndarray                 # MCTR_i = (Σw)_i / sigma_p
    component: np.ndarray                # CCTR_i = w_i * MCTR_i  (sum == sigma_p)
    percentage: np.ndarray               # PCTR_i = CCTR_i / sigma_p (sum == 1)

    def euler_check(self) -> float:
        """Residual of the Euler identity sum(CCTR) - sigma_p; should be ~0."""
        return float(self.component.sum() - self.portfolio_volatility)


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> RiskContribution:
    """Decompose portfolio volatility into per-holding contributions.

    MCTR = (Σ w) / sigma_p ;  CCTR = w * MCTR ;  PCTR = CCTR / sigma_p .
    By Euler's theorem (sigma_p is homogeneous degree 1 in w), sum(CCTR) == sigma_p exactly.
    """
    w = normalize_weights(weights)
    cov = np.asarray(cov, dtype=float)

    sigma = float(np.sqrt(max(w @ cov @ w, 0.0)))
    if sigma == 0.0:
        n = len(w)
        return RiskContribution(0.0, np.zeros(n), np.zeros(n), np.zeros(n))

    marginal = (cov @ w) / sigma
    component = w * marginal
    percentage = component / sigma
    return RiskContribution(sigma, marginal, component, percentage)


def bootstrap_risk_contributions(returns: np.ndarray, weights: np.ndarray,
                                 n_boot: int = 400, block: int = 4,
                                 alpha: float = 0.90, seed: int = 12345) -> dict:
    """Block-bootstrap confidence intervals for percentage risk contributions (PCTR).

    MCTR/PCTR are point estimates off a noisy covariance; without error bars they can be
    over-read. We resample overlapping blocks of the return history (preserving short-run
    autocorrelation), recompute PCTR on each resample, and report the central estimate with
    a (100*alpha)% percentile interval per holding.
    """
    from .portfolio import covariance_matrix, normalize_weights  # local import avoids cycle

    X = np.asarray(returns, dtype=float)
    T, n = X.shape
    w = normalize_weights(weights)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(T / block))

    samples = np.zeros((n_boot, n))
    for b in range(n_boot):
        starts = rng.integers(0, max(T - block, 1), size=n_blocks)
        idx = np.concatenate([np.arange(s, min(s + block, T)) for s in starts])[:T]
        rc = risk_contributions(w, covariance_matrix(X[idx]))
        samples[b] = rc.percentage

    lo = np.quantile(samples, (1 - alpha) / 2, axis=0)
    hi = np.quantile(samples, 1 - (1 - alpha) / 2, axis=0)
    point = risk_contributions(w, covariance_matrix(X)).percentage
    return {"point": point, "lower": lo, "upper": hi, "confidence": alpha}


def conditional_risk_contributions(weights: np.ndarray, calm_cov: np.ndarray,
                                   stressed_cov: np.ndarray) -> dict:
    """Compare risk attribution under the normal-times vs. the crisis-regime covariance.

    This is the fix for scenario-agnostic attribution: because correlations rise in a
    crisis, a holding's *share of risk* shifts. Reporting both makes the change explicit -
    e.g. a credit holding that looks benign in calm times can dominate risk under stress.
    """
    calm = risk_contributions(weights, calm_cov)
    stressed = risk_contributions(weights, stressed_cov)
    n = len(calm.percentage)
    return {
        "calm": calm,
        "stressed": stressed,
        "pctr_shift": (stressed.percentage - calm.percentage),  # + == holding gets riskier in stress
        "n": n,
    }
