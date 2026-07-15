"""Deterministic investment-commentary generation.

Turns computed numbers into a portfolio-manager narrative. Fully template-driven
(auditable, reproducible, no LLM). See docs/METHODOLOGY.md.
"""
from __future__ import annotations


def _pct(x: float, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%"


def _bps(x: float) -> str:
    return f"{x * 1e4:+.0f}bps"


def _fmt_shock(name: str, val: float) -> str:
    if name in ("Rates", "Credit"):
        return f"{name} {_bps(val)}"
    return f"{name} {_pct(val)}"


def stress_commentary(*, scenario_name: str, portfolio_drawdown: float,
                      factor_pnl: dict[str, float], worst_holding: str,
                      worst_holding_pctr: float, worst_holding_weight: float,
                      worst_holding_pctr_shift: float, var_gaussian: float,
                      var_historical: float, rebalance) -> str:
    """Multi-sentence narrative: outcome, driver, blame (regime-aware), tail risk, and fix."""
    dominant_factor, dominant_pnl = min(factor_pnl.items(), key=lambda kv: kv[1])

    parts: list[str] = []
    parts.append(
        f"Under the {scenario_name} scenario, the portfolio would draw down "
        f"{_pct(abs(portfolio_drawdown))}, driven primarily by the {dominant_factor} factor "
        f"({_pct(dominant_pnl)} of the move)."
    )
    shift_note = ""
    if worst_holding_pctr_shift > 0.02:
        shift_note = (f" - and its risk share rises {_pct(worst_holding_pctr_shift)} moving from "
                      f"the calm regime to the crisis regime, because correlations tighten in stress")
    parts.append(
        f"In the crisis regime, {worst_holding} is the single largest source of portfolio "
        f"risk: {_pct(worst_holding_weight)} of capital but {_pct(worst_holding_pctr)} of "
        f"risk{shift_note}."
    )
    if var_historical > var_gaussian * 1.05:
        parts.append(
            f"Note the tail: historical 1-week VaR ({_pct(var_historical)}) exceeds the "
            f"Gaussian estimate ({_pct(var_gaussian)}) by {_pct(var_historical - var_gaussian)}, "
            f"so a normal-distribution model understates the downside here."
        )

    if rebalance.applied:
        parts.append(
            f"Recommended mitigation: {rebalance.reason} Projected to cut the scenario drawdown by "
            f"{_pct(rebalance.drawdown_improvement)} (from {_pct(rebalance.old_drawdown)} to "
            f"{_pct(rebalance.new_drawdown)}) and change crisis-regime volatility by "
            f"{_pct(rebalance.volatility_change)}."
        )
    else:
        parts.append(
            "No single-trade rebalance materially improves this scenario; the current "
            "allocation is already reasonably resilient to this shock."
        )
    return " ".join(parts)


def reverse_commentary(*, target_loss: float, shocks: dict[str, float],
                       mahalanobis_distance: float, constrained: bool,
                       top_alternative: dict | None) -> str:
    """Narrate the reverse-stress result: the most plausible path to a target loss."""
    ordered = sorted(shocks.items(), key=lambda kv: -abs(kv[1]))
    descriptors = [_fmt_shock(n, v) for n, v in ordered if abs(v) > 1e-6]
    combo = ", ".join(descriptors[:4]) if descriptors else "no material factor move"

    basis = "within plausible per-factor bounds" if constrained else "unconstrained"
    text = (
        f"The most plausible path to a {_pct(target_loss)} loss ({basis}) is a joint move of "
        f"{combo}. This sits roughly {mahalanobis_distance:.1f} standard deviations from normal "
        f"factor behaviour - a lower number means a more plausible, and more concerning, loss."
    )
    if top_alternative:
        alt = top_alternative
        alt_desc = ", ".join(_fmt_shock(n, v) for n, v in alt["shocks"].items() if abs(v) > 1e-6)
        text += (f" Alternatively, the loss could arrive almost entirely through "
                 f"{alt['dominant_factor']} ({alt_desc}).")
    return text
