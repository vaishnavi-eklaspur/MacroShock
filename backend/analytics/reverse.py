"""Reverse stress testing.

Given a target portfolio loss L*, find factor-shock vectors s that produce it. We provide:

  1. Closed-form minimum-Mahalanobis solution (unconstrained):
         s* = -L* · (Σ_F g) / (gᵀ Σ_F g),   g = Bᵀ w
     the single most-plausible shock (smallest Mahalanobis distance) hitting the loss.

  2. A CONSTRAINED solution: same objective but with per-factor plausibility bounds and
     sign constraints (e.g. credit spreads can't collapse), solved by SLSQP. This stops the
     "most plausible" answer from returning economically nonsensical shock combinations.

  3. TOP-K alternative narratives: for each factor, the pure single-factor path to the loss,
     ranked by plausibility - "the loss could come via a -X% equity crash, OR a +Ybps credit
     blowout, ..." with a plausibility (Mahalanobis) score for each.

See docs/METHODOLOGY.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from .portfolio import normalize_weights

# Per-factor plausibility bounds (native units). Editable / documented assumptions.
DEFAULT_BOUNDS: dict[str, tuple[float, float]] = {
    "Equity": (-0.60, 0.60),
    "Rates": (-0.04, 0.04),
    "Credit": (-0.02, 0.08),      # spreads rarely tighten sharply; can blow out a lot
    "Commodity": (-0.70, 0.70),
    "Liquidity": (-0.50, 0.20),   # liquidity worsens (negative) far more than it improves
    "FX": (-0.25, 0.25),
}


def _mahalanobis(s: np.ndarray, factor_cov: np.ndarray) -> float:
    return float(np.sqrt(max(s @ np.linalg.solve(factor_cov, s), 0.0)))


@dataclass
class ReverseStressResult:
    shocks: dict[str, float]              # primary (constrained) most-plausible shocks
    unconstrained_shocks: dict[str, float]
    gradient: dict[str, float]
    target_loss: float
    implied_loss: float
    mahalanobis_distance: float
    constrained: bool                     # whether bounds were applied successfully
    alternatives: list[dict] = field(default_factory=list)  # top-k single-factor narratives
    factor_order: list[str] = field(default_factory=list)


def reverse_stress(weights: np.ndarray, exposure_matrix: np.ndarray,
                   factor_cov: np.ndarray, target_loss: float,
                   factor_names: list[str],
                   bounds: dict[str, tuple[float, float]] | None = None,
                   top_k: int = 3) -> ReverseStressResult:
    """Solve for the most-plausible factor shock producing a target loss, with alternatives."""
    w = normalize_weights(weights)
    B = np.asarray(exposure_matrix, dtype=float)
    Sigma_F = np.asarray(factor_cov, dtype=float)
    bounds = bounds or DEFAULT_BOUNDS

    g = B.T @ w
    Sg = Sigma_F @ g
    denom = float(g @ Sg)
    if denom == 0.0:
        raise ValueError("Portfolio has no factor exposure; reverse stress is undefined.")

    # (1) Closed-form unconstrained minimum-Mahalanobis solution.
    s_unc = (-target_loss) * Sg / denom

    # (2) Constrained solve: min sᵀ Σ_F⁻¹ s s.t. gᵀ s = -L*, lb <= s <= ub.
    Sigma_inv = np.linalg.inv(Sigma_F)
    bnds = [bounds.get(name, (-1.0, 1.0)) for name in factor_names]

    def objective(s):
        return float(s @ Sigma_inv @ s)

    def objective_grad(s):
        return 2.0 * (Sigma_inv @ s)

    constraint = {"type": "eq", "fun": lambda s: float(g @ s + target_loss),
                  "jac": lambda s: g}
    x0 = np.clip(s_unc, [b[0] for b in bnds], [b[1] for b in bnds])
    res = minimize(objective, x0, jac=objective_grad, bounds=bnds,
                   constraints=[constraint], method="SLSQP",
                   options={"maxiter": 200, "ftol": 1e-12})
    if res.success and abs(float(g @ res.x) + target_loss) < 1e-6:
        s_primary, constrained = res.x, True
    else:
        s_primary, constrained = s_unc, False  # fall back to closed form

    # (3) Top-k single-factor narratives, ranked by plausibility (lower Mahalanobis = more likely).
    alternatives: list[dict] = []
    for j, name in enumerate(factor_names):
        if abs(g[j]) < 1e-12:
            continue
        s_j = np.zeros(len(factor_names))
        s_j[j] = -target_loss / g[j]
        alternatives.append({
            "dominant_factor": name,
            "shocks": {n: float(v) for n, v in zip(factor_names, s_j)},
            "mahalanobis_distance": _mahalanobis(s_j, Sigma_F),
        })
    alternatives.sort(key=lambda a: a["mahalanobis_distance"])
    alternatives = alternatives[:top_k]

    return ReverseStressResult(
        shocks={n: float(v) for n, v in zip(factor_names, s_primary)},
        unconstrained_shocks={n: float(v) for n, v in zip(factor_names, s_unc)},
        gradient={n: float(v) for n, v in zip(factor_names, g)},
        target_loss=float(target_loss),
        implied_loss=float(-(g @ s_primary)),
        mahalanobis_distance=_mahalanobis(s_primary, Sigma_F),
        constrained=constrained,
        alternatives=alternatives,
        factor_order=list(factor_names),
    )
