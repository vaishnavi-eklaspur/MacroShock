"""Orchestration engine: composes the analytics over data-layer inputs.

Produces JSON-serializable result dictionaries consumed by the Flask API and Streamlit UI.
Loads the (expensive) historical data, shrinkage covariance, and regime-conditional
covariance once and reuses them.
"""
from __future__ import annotations

import numpy as np

from data import database
from data.reference import MODEL_VERSION

from . import backtest as backtest_mod
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

        # Unconditional (full-sample) covariance with Ledoit-Wolf shrinkage.
        self.cov, self.shrinkage = portfolio.ledoit_wolf_covariance(self.asset_returns)
        # Regime-conditional (crisis) covariance - correlations rise under stress.
        self.crisis_mask = regime.crisis_mask(self.asset_returns)
        self.stressed_cov = regime.conditional_covariance(self.asset_returns, self.crisis_mask)
        self.regime_summary = regime.regime_summary(self.asset_returns)

        # Factor covariance for reverse stress.
        self.factor_cov = factors.factor_weekly_covariance(self.factor_returns)
        self.exposure = factors.exposure_matrix(self.assets)

        self.scenarios = {s["scenario_id"]: s for s in database.get_scenarios(self.db_path)}
        self.realized = database.get_realized_crisis_returns(self.db_path)

    # ------------------------------------------------------------------ helpers
    def weight_vector(self, weights: dict[str, float]) -> np.ndarray:
        """Align a {ticker: weight} dict to canonical asset order and normalize."""
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
            "regime": self.regime_summary,
            "factors": self.factor_names,
        }

    # ------------------------------------------------------------------ analytics
    def risk_report(self, weights: dict[str, float]) -> dict:
        w = self.weight_vector(weights)
        cond = risk.conditional_risk_contributions(w, self.cov, self.stressed_cov)
        calm, stressed = cond["calm"], cond["stressed"]
        return {
            "tickers": self.tickers,
            "weights": {t: float(x) for t, x in zip(self.tickers, w)},
            "calm_volatility_weekly": calm.portfolio_volatility,
            "stressed_volatility_weekly": stressed.portfolio_volatility,
            "calm_percentage_contribution": dict(zip(self.tickers, calm.percentage.tolist())),
            "stressed_percentage_contribution": dict(zip(self.tickers, stressed.percentage.tolist())),
            "pctr_shift": dict(zip(self.tickers, cond["pctr_shift"].tolist())),
            "euler_residual": stressed.euler_check(),
        }

    def factor_regression(self, weights: dict[str, float]) -> dict:
        w = self.weight_vector(weights)
        port_series = self.asset_returns @ w
        reg = factors.ols_factor_betas(port_series, self.factor_returns, self.factor_names)
        return {
            "alpha": reg.alpha, "alpha_t_stat": reg.alpha_t_stat,
            "betas": reg.betas, "t_stats": reg.t_stats, "std_errors": reg.std_errors,
            "r_squared": reg.r_squared, "adj_r_squared": reg.adj_r_squared,
        }

    def _var_suite(self, w: np.ndarray, alpha: float) -> dict:
        sigma = portfolio.portfolio_volatility(w, self.cov)  # weekly, unconditional
        series = self.asset_returns @ w
        moments = portfolio.sample_moments(series)
        return {
            "horizon": "weekly",
            "confidence": alpha,
            "volatility_weekly": sigma,
            "volatility_annual": portfolio.annualize_volatility(sigma),
            "moments": moments,
            "var": {
                "gaussian": portfolio.parametric_var(sigma, alpha),
                "student_t": portfolio.student_t_var(sigma, alpha, dof=5.0),
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
        scenario = self.scenarios[scenario_id]
        shocks = scenario["shocks"]
        w = self.weight_vector(weights)

        # Scenario pricing.
        asset_scn = factors.scenario_asset_returns(self.assets, shocks)
        portfolio_drawdown = float(w @ asset_scn)
        factor_pnl = factors.factor_pnl_breakdown(self.assets, w, shocks)

        # Risk metrics (fat-tailed suite) + regime-conditional attribution.
        var_suite = self._var_suite(w, alpha)
        cond = risk.conditional_risk_contributions(w, self.cov, self.stressed_cov)
        calm_rc, stressed_rc = cond["calm"], cond["stressed"]

        # Mitigation uses the STRESSED covariance so the vol improvement is scenario-relevant.
        rec = rebalance.recommend_rebalance(w, self.tickers, asset_scn, self.stressed_cov)

        # Worst holding by CRISIS-regime risk share (this is what "to blame" means in a crisis).
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
            rebalance=rec,
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
            "rebalance": _rebalance_dict(rec),
            "commentary": narrative,
        }

    def reverse_stress(self, weights: dict[str, float], target_loss: float) -> dict:
        w = self.weight_vector(weights)
        res = reverse.reverse_stress(
            weights=w, exposure_matrix=self.exposure, factor_cov=self.factor_cov,
            target_loss=target_loss, factor_names=self.factor_names,
        )
        narrative = commentary.reverse_commentary(
            target_loss=target_loss, shocks=res.shocks,
            mahalanobis_distance=res.mahalanobis_distance,
            constrained=res.constrained,
            top_alternative=res.alternatives[0] if res.alternatives else None,
        )
        return {
            "shocks": res.shocks,
            "unconstrained_shocks": res.unconstrained_shocks,
            "gradient": res.gradient,
            "target_loss": res.target_loss,
            "implied_loss": res.implied_loss,
            "mahalanobis_distance": res.mahalanobis_distance,
            "constrained": res.constrained,
            "alternatives": res.alternatives,
            "factor_order": res.factor_order,
            "commentary": narrative,
        }

    def backtest(self) -> dict:
        return backtest_mod.backtest_all(self.assets, self.tickers, self.scenarios, self.realized)


def _rebalance_dict(rec) -> dict:
    """Explicit serialization of the rebalance recommendation (no __dict__ leakage)."""
    return {
        "applied": rec.applied, "reason": rec.reason,
        "from_ticker": rec.from_ticker, "to_ticker": rec.to_ticker, "shift": rec.shift,
        "old_weights": rec.old_weights, "new_weights": rec.new_weights,
        "old_drawdown": rec.old_drawdown, "new_drawdown": rec.new_drawdown,
        "drawdown_improvement": rec.drawdown_improvement,
        "old_volatility": rec.old_volatility, "new_volatility": rec.new_volatility,
        "volatility_change": rec.volatility_change,
    }
