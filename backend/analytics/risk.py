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
