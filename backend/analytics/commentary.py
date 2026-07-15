"""Deterministic investment-commentary generation.

Turns the computed numbers into a portfolio-manager narrative. Fully template-driven
(auditable, reproducible, no LLM). See docs/METHODOLOGY.md section 10.
"""
from __future__ import annotations


def _pct(x: float, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%"


def _bps(x: float) -> str:
    return f"{x * 1e4:+.0f}bps"


def stress_commentary(*, scenario_name: str, portfolio_drawdown: float,
                      factor_pnl: dict[str, float], worst_holding: str,
                      worst_holding_pctr: float, worst_holding_weight: float,
                      rebalance) -> str:
    """Build a multi-sentence narrative explaining the scenario outcome and the fix."""
    # Dominant loss factor (most negative P&L contribution).
    dominant_factor, dominant_pnl = min(factor_pnl.items(), key=lambda kv: kv[1])

    parts: list[str] = []
    parts.append(
        f"Under the {scenario_name} scenario, the portfolio would draw down "
        f"{_pct(abs(portfolio_drawdown))}."
    )
    parts.append(
        f"The dominant driver is the {dominant_factor} factor, contributing "
        f"{_pct(dominant_pnl)} of the move."
    )
    parts.append(
        f"On a standalone risk basis, {worst_holding} is the single largest source of "
        f"portfolio volatility: it is {_pct(worst_holding_weight)} of capital but "
        f"{_pct(worst_holding_pctr)} of total risk - a concentration worth noting."
    )

    if rebalance.applied:
        parts.append(
            f"Recommended mitigation: {rebalance.reason} This is projected to reduce the "
            f"scenario drawdown by {_pct(rebalance.drawdown_improvement)} "
            f"(from {_pct(rebalance.old_drawdown)} to {_pct(rebalance.new_drawdown)}) and "
            f"change portfolio volatility by {_pct(rebalance.volatility_change)}."
        )
    else:
        parts.append(
            "No single-trade rebalance improves this scenario materially; the current "
            "allocation is already reasonably resilient to this shock."
        )

    return " ".join(parts)


def reverse_commentary(*, target_loss: float, shocks: dict[str, float],
                       mahalanobis_distance: float) -> str:
    """Narrate the reverse-stress result: the most plausible path to a target loss."""
    # Order factors by absolute shock magnitude for readability.
    ordered = sorted(shocks.items(), key=lambda kv: -abs(kv[1]))
    descriptors = []
    for name, val in ordered:
        if abs(val) < 1e-9:
            continue
        if name in ("Rates", "Credit"):
            descriptors.append(f"{name} {_bps(val)}")
        else:
            descriptors.append(f"{name} {_pct(val)}")

    combo = ", ".join(descriptors) if descriptors else "no material factor move"
    return (
        f"The most plausible path to a {_pct(target_loss)} loss is a joint move of "
        f"{combo}. This scenario sits roughly {mahalanobis_distance:.1f} standard deviations "
        f"from normal factor behaviour - the lower this number, the more plausible (and "
        f"therefore concerning) the loss."
    )
