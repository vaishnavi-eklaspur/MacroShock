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


# Return-space factors are floored at -100% (an asset/index cannot lose more than everything).
RETURN_FACTORS = {"Equity", "Commodity", "Liquidity", "FX"}


@dataclass
class ReverseStressResult:
    shocks: dict[str, float]              # primary (constrained) most-plausible shocks
    unconstrained_shocks: dict[str, float]
    gradient: dict[str, float]
    target_loss: float
    implied_loss: float
    mahalanobis_distance: float
    constrained: bool                     # whether bounds were applied successfully
    reachable: bool                       # whether the target loss is attainable within bounds
    max_loss_within_bounds: float         # worst loss achievable with plausible factor moves
    plausibility_note: str = ""
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

    bnds = [bounds.get(name, (-1.0, 1.0)) for name in factor_names]

    # Maximum loss attainable within the plausible factor bounds: for each factor, take the
    # bound (lb/ub) that maximizes the loss -g_k*s_k. If the target exceeds this, no plausible
    # scenario reaches it - we must say so rather than returning an absurd shock.
    max_loss = 0.0
    max_loss_shock = np.zeros(len(factor_names))
    for k, (lb, ub) in enumerate(bnds):
        loss_lb, loss_ub = -g[k] * lb, -g[k] * ub
        if loss_lb >= loss_ub:
            max_loss += loss_lb; max_loss_shock[k] = lb
        else:
            max_loss += loss_ub; max_loss_shock[k] = ub
    reachable = target_loss <= max_loss + 1e-9

    # (1) Closed-form unconstrained minimum-Mahalanobis solution (reference only).
    s_unc = (-target_loss) * Sg / denom

    # (2) Constrained solve: min sᵀ Σ_F⁻¹ s s.t. gᵀ s = -L*, lb <= s <= ub.
    Sigma_inv = np.linalg.inv(Sigma_F)
    if reachable:
        def objective(s):
            return float(s @ Sigma_inv @ s)

        def objective_grad(s):
            return 2.0 * (Sigma_inv @ s)

        constraint = {"type": "eq", "fun": lambda s: float(g @ s + target_loss),
                      "jac": lambda s: g}
        x0 = np.clip(s_unc, [b[0] for b in bnds], [b[1] for b in bnds])
        res = minimize(objective, x0, jac=objective_grad, bounds=bnds,
                       constraints=[constraint], method="SLSQP",
                       options={"maxiter": 300, "ftol": 1e-12})
        if res.success and abs(float(g @ res.x) + target_loss) < 1e-6:
            s_primary, constrained = res.x, True
        else:
            s_primary, constrained = np.clip(s_unc, [b[0] for b in bnds], [b[1] for b in bnds]), False
    else:
        # Target unreachable within bounds: report the worst *plausible* loss instead.
        s_primary, constrained = max_loss_shock, True

    maha = _mahalanobis(s_primary, Sigma_F)
    if not reachable:
        note = (f"No scenario within plausible factor bounds reaches a {target_loss*100:.0f}% "
                f"loss. The worst plausible loss for this portfolio is ~{max_loss*100:.0f}%.")
    elif maha > 4.0:
        note = (f"Even the least-implausible path is a {maha:.1f}-sigma event - effectively "
                f"unreachable under normal factor behaviour. This is reassuring, not a forecast.")
    else:
        note = ""

    # (3) Top-k single-factor narratives. Each is flagged for feasibility within bounds;
    # infeasible ones (e.g. a >100% commodity move) are labelled, never presented as plausible.
    alternatives: list[dict] = []
    for j, name in enumerate(factor_names):
        if abs(g[j]) < 1e-12:
            continue
        raw = -target_loss / g[j]
        lb, ub = bnds[j]
        feasible = lb - 1e-9 <= raw <= ub + 1e-9
        if name in RETURN_FACTORS and raw < -1.0:
            feasible = False
        s_j = np.zeros(len(factor_names)); s_j[j] = raw
        alternatives.append({
            "dominant_factor": name,
            "shock_value": float(raw),
            "shocks": {n: float(v) for n, v in zip(factor_names, s_j)},
            "mahalanobis_distance": _mahalanobis(s_j, Sigma_F),
            "feasible_within_bounds": bool(feasible),
        })
    # Feasible first, then by plausibility.
    alternatives.sort(key=lambda a: (not a["feasible_within_bounds"], a["mahalanobis_distance"]))
    alternatives = alternatives[:top_k]

    return ReverseStressResult(
        shocks={n: float(v) for n, v in zip(factor_names, s_primary)},
        unconstrained_shocks={n: float(v) for n, v in zip(factor_names, s_unc)},
        gradient={n: float(v) for n, v in zip(factor_names, g)},
        target_loss=float(target_loss),
        implied_loss=float(-(g @ s_primary)),
        mahalanobis_distance=maha,
        constrained=constrained,
        reachable=bool(reachable),
        max_loss_within_bounds=float(max_loss),
        plausibility_note=note,
        alternatives=alternatives,
        factor_order=list(factor_names),
    )
