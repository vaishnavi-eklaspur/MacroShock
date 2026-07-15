"""Orchestration engine: composes the analytics over data-layer inputs.

Produces JSON-serializable result dictionaries for the Flask API and Streamlit UI. Loads the
expensive objects once: constant-correlation shrinkage covariance, crisis-regime conditional
covariance (assets and factors), and the exposure matrix.
"""
from __future__ import annotations

import numpy as np

from data import database
from data.reference import BENCHMARKS, MODEL_VERSION

from . import backtest as backtest_mod
from . import benchmark as benchmark_mod
from . import commentary, factors, portfolio, rebalance, regime, reverse, risk


class MacroShockEngine:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path
        self.model_version = MODEL_VERSION
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        self.assets = database.get_assets(self.db_path)
        self.tickers: list[str] = self.assets["ticker"].tolist()
        self.factor_names = factors.FACTOR_ORDER

        asset_rets = database.get_asset_returns(self.db_path)[self.tickers]
        factor_rets = database.get_factor_returns(self.db_path)[self.factor_names]
        self.asset_returns = asset_rets.to_numpy()
        self.factor_returns = factor_rets.to_numpy()

        # Unconditional covariance: constant-correlation Ledoit-Wolf shrinkage.
        self.cov, self.shrinkage = portfolio.ledoit_wolf_constant_correlation(self.asset_returns)

        # Crisis-regime conditional covariances (assets + factors), same detected crisis weeks.
        self.crisis_mask = regime.crisis_mask(self.asset_returns)
        self.stressed_cov, self.stressed_fallback = regime.conditional_covariance(
            self.asset_returns, self.crisis_mask)
        self.crisis_factor_cov, self.factor_fallback = regime.conditional_covariance(
            self.factor_returns, self.crisis_mask)
        self.regime_summary = regime.regime_summary(self.asset_returns)

        # Full-sample factor covariance (reference) and exposure matrix.
        self.factor_cov = factors.factor_weekly_covariance(self.factor_returns)
        self.exposure = factors.exposure_matrix(self.assets)          # structural (hand-set)

        # Data-driven exposures: OLS betas estimated on the weekly history. Because they are
        # fit on normal-times returns and the crisis realized returns are independent, using
        # these in the backtest makes it genuinely out-of-sample (no beta leakage).
        self.exposure_estimated, self.exposure_r2 = factors.estimate_exposures(
            self.asset_returns, self.factor_returns)

        self.scenarios = {s["scenario_id"]: s for s in database.get_scenarios(self.db_path)}
        self.realized = database.get_realized_crisis_returns(self.db_path)
        self.dataset_meta = database.get_dataset_meta(self.db_path)

    # ------------------------------------------------------------------ helpers
    def weight_vector(self, weights: dict[str, float]) -> np.ndarray:
        w = np.array([float(weights.get(t, 0.0)) for t in self.tickers])
        return portfolio.normalize_weights(w)

    def list_scenarios(self) -> list[dict]:
        return [dict(s) for s in self.scenarios.values()]

    def asset_reference(self) -> list[dict]:
        return self.assets.to_dict(orient="records")

    def meta(self) -> dict:
        return {
            "model_version": self.model_version,
            "shrinkage_intensity": self.shrinkage,
            "shrinkage_target": "constant-correlation (Ledoit-Wolf 2003)",
            "regime": self.regime_summary,
            "crisis_cov_used_fallback": bool(self.stressed_fallback),
            "factors": self.factor_names,
            "dataset": self.dataset_meta,
            "estimated_exposure_r2_mean": float(np.mean(self.exposure_r2)),
        }

    def exposure_report(self) -> dict:
        """Structural (hand-set) vs. estimated (OLS) factor betas per asset, with per-asset R²."""
        struct, est = self.exposure, self.exposure_estimated
        return {
            "factors": self.factor_names,
            "assets": [
                {
                    "ticker": t,
                    "structural": dict(zip(self.factor_names, struct[i].tolist())),
                    "estimated": dict(zip(self.factor_names, est[i].tolist())),
                    "r_squared": float(self.exposure_r2[i]),
                }
                for i, t in enumerate(self.tickers)
            ],
            "r2_mean": float(np.mean(self.exposure_r2)),
            "note": "Estimated betas are OLS fits on the weekly return history against "
                    "independent factor series; R² well below 1.0 confirms the factors are not "
                    "a rotation of the assets. Scenario pricing uses the interpretable "
                    "structural matrix; the backtest uses the estimated one (no leakage).",
        }

    # ------------------------------------------------------------------ analytics
    def risk_report(self, weights: dict[str, float]) -> dict:
        w = self.weight_vector(weights)
        cond = risk.conditional_risk_contributions(w, self.cov, self.stressed_cov)
        calm, stressed = cond["calm"], cond["stressed"]
        boot = risk.bootstrap_risk_contributions(self.asset_returns, w)
        return {
            "tickers": self.tickers,
            "weights": {t: float(x) for t, x in zip(self.tickers, w)},
            "calm_volatility_weekly": calm.portfolio_volatility,
            "stressed_volatility_weekly": stressed.portfolio_volatility,
            "calm_percentage_contribution": dict(zip(self.tickers, calm.percentage.tolist())),
            "stressed_percentage_contribution": dict(zip(self.tickers, stressed.percentage.tolist())),
            "pctr_shift": dict(zip(self.tickers, cond["pctr_shift"].tolist())),
            "pctr_confidence_interval": {
                t: {"point": float(p), "lower": float(lo), "upper": float(hi)}
                for t, p, lo, hi in zip(self.tickers, boot["point"], boot["lower"], boot["upper"])
            },
            "pctr_ci_confidence": boot["confidence"],
            "euler_residual": stressed.euler_check(),
            "crisis_cov_used_fallback": bool(self.stressed_fallback),
        }

    def factor_regression(self, weights: dict[str, float], ridge_lambda: float = 0.0) -> dict:
        w = self.weight_vector(weights)
        port_series = self.asset_returns @ w
        reg = factors.ols_factor_betas(port_series, self.factor_returns, self.factor_names,
                                       ridge_lambda=ridge_lambda)
        return {
            "alpha": reg.alpha, "alpha_t_stat": reg.alpha_t_stat,
            "betas": reg.betas, "t_stats": reg.t_stats, "std_errors": reg.std_errors,
            "r_squared": reg.r_squared, "adj_r_squared": reg.adj_r_squared,
            "vif": reg.vif, "condition_number": reg.condition_number,
            "ridge_lambda": reg.ridge_lambda,
        }

    def _var_suite(self, w: np.ndarray, alpha: float) -> dict:
        sigma = portfolio.portfolio_volatility(w, self.cov)   # weekly, unconditional
        series = self.asset_returns @ w                       # computed once
        moments = portfolio.sample_moments(series)
        fitted_dof = portfolio.fit_student_t_dof(series)
        cf_valid = portfolio.cornish_fisher_valid(series)
        return {
            "horizon": "weekly",
            "confidence": alpha,
            "volatility_weekly": sigma,
            "volatility_annual": portfolio.annualize_volatility(sigma),
            "moments": moments,
            "fitted_student_t_dof": fitted_dof,
            "normality_test": portfolio.jarque_bera(series),
            "cornish_fisher_valid": cf_valid,
            "var": {
                "gaussian": portfolio.parametric_var(sigma, alpha),
                "student_t": portfolio.student_t_var(sigma, alpha, dof=fitted_dof),
                "cornish_fisher": portfolio.cornish_fisher_var(series, alpha),
                "historical": portfolio.historical_var(series, alpha),
            },
            "cvar": {
                "gaussian": portfolio.parametric_cvar(sigma, alpha),
                "historical": portfolio.historical_cvar(series, alpha),
            },
        }

    def stress_test(self, weights: dict[str, float], scenario_id: str,
                    alpha: float = 0.95) -> dict:
        if scenario_id not in self.scenarios:
            raise KeyError(f"Unknown scenario_id '{scenario_id}'")
        return self._stress(weights, self.scenarios[scenario_id], alpha)

    def custom_stress_test(self, weights: dict[str, float], shocks: dict[str, float],
                           name: str = "Custom scenario", alpha: float = 0.95) -> dict:
        """Stress-test against a user-defined factor-shock vector (the scenario builder)."""
        scenario = {
            "scenario_id": "CUSTOM", "name": name,
            "description": "User-defined factor shocks.", "is_historical": False,
            "shocks": {f: float(shocks.get(f, 0.0)) for f in self.factor_names},
        }
        return self._stress(weights, scenario, alpha)

    def _stress(self, weights: dict[str, float], scenario: dict, alpha: float = 0.95) -> dict:
        scenario_id = scenario["scenario_id"]
        shocks = scenario["shocks"]
        w = self.weight_vector(weights)

        asset_scn = factors.scenario_asset_returns(self.assets, shocks)
        portfolio_drawdown = float(w @ asset_scn)
        factor_pnl = factors.factor_pnl_breakdown(self.assets, w, shocks)

        var_suite = self._var_suite(w, alpha)
        cond = risk.conditional_risk_contributions(w, self.cov, self.stressed_cov)
        calm_rc, stressed_rc = cond["calm"], cond["stressed"]

        # Constrained-optimization mitigation on the crisis-regime covariance.
        opt = rebalance.optimize_rebalance(w, self.tickers, asset_scn, self.stressed_cov)

        stressed_pctr = stressed_rc.percentage
        worst_idx = int(np.argmax(stressed_pctr))

        narrative = commentary.stress_commentary(
            scenario_name=scenario["name"],
            portfolio_drawdown=portfolio_drawdown,
            factor_pnl=factor_pnl,
            worst_holding=self.tickers[worst_idx],
            worst_holding_pctr=float(stressed_pctr[worst_idx]),
            worst_holding_weight=float(w[worst_idx]),
            worst_holding_pctr_shift=float(cond["pctr_shift"][worst_idx]),
            var_gaussian=var_suite["var"]["gaussian"],
            var_historical=var_suite["var"]["historical"],
            rebalance=opt,
        )

        return {
            "scenario": {"scenario_id": scenario_id, "name": scenario["name"],
                          "description": scenario["description"], "shocks": shocks,
                          "is_historical": scenario["is_historical"]},
            "weights": {t: float(x) for t, x in zip(self.tickers, w)},
            "portfolio_drawdown": portfolio_drawdown,
            "per_asset_scenario_return": dict(zip(self.tickers, asset_scn.tolist())),
            "per_asset_pnl_contribution": dict(zip(self.tickers, (w * asset_scn).tolist())),
            "factor_pnl_attribution": factor_pnl,
            "risk": var_suite,
            "risk_contribution": {
                "calm_percentage": dict(zip(self.tickers, calm_rc.percentage.tolist())),
                "stressed_percentage": dict(zip(self.tickers, stressed_pctr.tolist())),
                "pctr_shift": dict(zip(self.tickers, cond["pctr_shift"].tolist())),
            },
            "rebalance": _optimized_rebalance_dict(opt),
            "commentary": narrative,
        }

    def reverse_stress(self, weights: dict[str, float], target_loss: float) -> dict:
        w = self.weight_vector(weights)
        # Use the CRISIS-regime factor covariance so plausibility is measured in the same
        # regime as the risk attribution (internally consistent).
        res = reverse.reverse_stress(
            weights=w, exposure_matrix=self.exposure, factor_cov=self.crisis_factor_cov,
            target_loss=target_loss, factor_names=self.factor_names,
        )
        narrative = commentary.reverse_commentary(
            target_loss=target_loss, shocks=res.shocks,
            mahalanobis_distance=res.mahalanobis_distance,
            constrained=res.constrained, reachable=res.reachable,
            max_loss_within_bounds=res.max_loss_within_bounds,
            plausibility_note=res.plausibility_note,
            top_alternative=next((a for a in res.alternatives
                                  if a.get("feasible_within_bounds")), None),
        )
        return {
            "shocks": res.shocks, "unconstrained_shocks": res.unconstrained_shocks,
            "gradient": res.gradient, "target_loss": res.target_loss,
            "implied_loss": res.implied_loss, "mahalanobis_distance": res.mahalanobis_distance,
            "constrained": res.constrained, "reachable": res.reachable,
            "max_loss_within_bounds": res.max_loss_within_bounds,
            "plausibility_note": res.plausibility_note,
            "alternatives": res.alternatives,
            "factor_order": res.factor_order, "covariance_regime": "crisis",
            "commentary": narrative,
        }

    def active_risk(self, weights: dict[str, float],
                    benchmark: dict[str, float] | str) -> dict:
        """Benchmark-relative analytics (tracking error, active risk, factor tilts)."""
        if isinstance(benchmark, str):
            if benchmark not in BENCHMARKS:
                raise KeyError(f"Unknown benchmark '{benchmark}'. Valid: {list(BENCHMARKS)}")
            bench_dict, bench_name = BENCHMARKS[benchmark], benchmark
        else:
            bench_dict, bench_name = benchmark, "custom"
        w = self.weight_vector(weights)
        wb = self.weight_vector(bench_dict)
        rep = benchmark_mod.active_analysis(w, wb, self.cov, self.stressed_cov, self.exposure,
                                            self.factor_names, self.tickers)
        rep["benchmark_name"] = bench_name
        rep["benchmark_weights"] = {t: float(x) for t, x in zip(self.tickers, wb)}
        return rep

    @staticmethod
    def benchmarks() -> dict[str, dict[str, float]]:
        return BENCHMARKS

    def backtest(self) -> dict:
        # Pass the ESTIMATED exposures (fit on weekly history) so the out-of-sample crisis
        # prediction never uses betas calibrated to the crises it is scored against.
        return backtest_mod.backtest_all(self.assets, self.tickers, self.scenarios,
                                         self.realized, exposure=self.exposure_estimated)


def _optimized_rebalance_dict(rec) -> dict:
    return {
        "applied": rec.applied, "method": rec.method, "reason": rec.method,
        "old_weights": rec.old_weights, "new_weights": rec.new_weights,
        "old_drawdown": rec.old_drawdown, "new_drawdown": rec.new_drawdown,
        "drawdown_improvement": rec.drawdown_improvement,
        "old_volatility": rec.old_volatility, "new_volatility": rec.new_volatility,
        "volatility_change": rec.volatility_change, "turnover": rec.turnover,
    }
