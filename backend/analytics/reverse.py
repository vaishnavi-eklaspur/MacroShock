"""Reverse stress testing.

Given a target portfolio loss L*, find the *most plausible* factor-shock vector s that
produces it: minimize the Mahalanobis distance sᵀ Σ_F⁻¹ s subject to the linear constraint
gᵀ s = -L*, where g = Bᵀ w is the portfolio's factor gradient.

Closed-form (single linear constraint, Lagrange multipliers):

    s* = -L* · (Σ_F g) / (gᵀ Σ_F g)

See docs/METHODOLOGY.md section 8.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .portfolio import normalize_weights


@dataclass
class ReverseStressResult:
    shocks: dict[str, float]         # most-plausible factor shocks (native units)
    gradient: dict[str, float]       # g_k = portfolio sensitivity to factor k
    target_loss: float               # L* requested (positive number)
    implied_loss: float              # loss actually produced by s* (should equal L*)
    mahalanobis_distance: float      # sqrt(sᵀ Σ_F⁻¹ s): "how many sigmas" the scenario is
    factor_order: list[str] = field(default_factory=list)


def reverse_stress(weights: np.ndarray, exposure_matrix: np.ndarray,
                   factor_cov: np.ndarray, target_loss: float,
                   factor_names: list[str]) -> ReverseStressResult:
    """Solve for the minimum-Mahalanobis factor shock producing a target loss.

    Parameters
    ----------
    weights : portfolio weights (n,)
    exposure_matrix : B (n_assets x n_factors), linear factor exposures
    factor_cov : Σ_F (n_factors x n_factors) factor covariance
    target_loss : positive number, e.g. 0.20 for a 20% loss
    """
    w = normalize_weights(weights)
    B = np.asarray(exposure_matrix, dtype=float)
    Sigma_F = np.asarray(factor_cov, dtype=float)

    g = B.T @ w                       # portfolio factor gradient  g = Bᵀ w
    Sg = Sigma_F @ g
    denom = float(g @ Sg)
    if denom == 0.0:
        raise ValueError("Portfolio has no factor exposure; reverse stress is undefined.")

    # Constraint gᵀ s = -L*  (a loss of L* means portfolio return R_p = -L*).
    s = (-target_loss) * Sg / denom

    implied = float(g @ s)            # == -target_loss by construction
    mahalanobis = float(np.sqrt(max(s @ np.linalg.solve(Sigma_F, s), 0.0)))

    return ReverseStressResult(
        shocks={name: float(v) for name, v in zip(factor_names, s)},
        gradient={name: float(v) for name, v in zip(factor_names, g)},
        target_loss=float(target_loss),
        implied_loss=float(-implied),  # report as a positive loss
        mahalanobis_distance=mahalanobis,
        factor_order=list(factor_names),
    )
