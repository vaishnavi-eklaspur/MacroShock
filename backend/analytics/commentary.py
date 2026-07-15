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

    method = getattr(rebalance, "reason", None) or getattr(rebalance, "method", "optimization")
    if rebalance.applied:
        parts.append(
            f"Recommended mitigation ({method}): projected to change crisis-regime volatility by "
            f"{_pct(rebalance.volatility_change)} while keeping the scenario drawdown no worse "
            f"({_pct(rebalance.new_drawdown)} vs {_pct(rebalance.old_drawdown)}), at "
            f"{_pct(getattr(rebalance, 'turnover', 0.0))} turnover."
        )
    else:
        parts.append(
            "The constrained optimizer finds no turnover-limited trade that reduces crisis "
            "risk without worsening the scenario; the current allocation is already efficient "
            "for this shock."
        )
    return " ".join(parts)


def reverse_commentary(*, target_loss: float, shocks: dict[str, float],
                       mahalanobis_distance: float, constrained: bool, reachable: bool,
                       max_loss_within_bounds: float, plausibility_note: str,
                       top_alternative: dict | None) -> str:
    """Narrate the reverse-stress result, distinguishing 'plausible' from 'least-implausible'."""
    if not reachable:
        return (f"No combination of factor moves within plausible bounds produces a "
                f"{_pct(target_loss)} loss. The worst plausible loss for this portfolio is "
                f"about {_pct(max_loss_within_bounds)} — i.e. this target is effectively "
                f"unreachable, which is a reassuring result, not a forecast.")

    ordered = sorted(shocks.items(), key=lambda kv: -abs(kv[1]))
    descriptors = [_fmt_shock(n, v) for n, v in ordered if abs(v) > 1e-6]
    combo = ", ".join(descriptors[:4]) if descriptors else "no material factor move"

    # "most plausible" only if it is actually plausible; otherwise "least-implausible".
    qualifier = "most plausible" if mahalanobis_distance <= 3.0 else "least-implausible"
    text = (
        f"The {qualifier} path to a {_pct(target_loss)} loss is a joint move of {combo}, "
        f"about {mahalanobis_distance:.1f} standard deviations from normal factor behaviour "
        f"(lower = more plausible)."
    )
    if plausibility_note:
        text += " " + plausibility_note
    if top_alternative:
        alt = top_alternative
        alt_desc = ", ".join(_fmt_shock(n, v) for n, v in alt["shocks"].items() if abs(v) > 1e-6)
        text += (f" Alternatively, the loss could arrive largely through "
                 f"{alt['dominant_factor']} ({alt_desc}).")
    return text
