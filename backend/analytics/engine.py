"""Orchestration engine: composes the analytics over data-layer inputs.

Produces JSON-serializable result dictionaries consumed by the Flask API and Streamlit UI.
Loads the (expensive) historical data and covariance matrices once and reuses them.
"""
from __future__ import annotations

import numpy as np

from data import database

from . import commentary, factors, portfolio, rebalance, reverse, risk


class MacroShockEngine:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        self.assets = database.get_assets(self.db_path)                 # ordered
        self.tickers: list[str] = self.assets["ticker"].tolist()
        self.factor_names = factors.FACTOR_ORDER

        asset_rets = database.get_asset_returns(self.db_path)[self.tickers]
        factor_rets = database.get_factor_returns(self.db_path)[self.factor_names]

        self.asset_returns = asset_rets.to_numpy()
        self.factor_returns = factor_rets.to_numpy()

        # Expensive objects computed once.
        self.cov = portfolio.covariance_matrix(self.asset_returns)          # asset covariance
        self.factor_cov = factors.factor_weekly_covariance(self.factor_returns)
        self.exposure = factors.exposure_matrix(self.assets)                # B matrix

        self.scenarios = {s["scenario_id"]: s for s in database.get_scenarios(self.db_path)}

    # ------------------------------------------------------------------ helpers
    def _weight_vector(self, weights: dict[str, float]) -> np.ndarray:
        """Align a {ticker: weight} dict to canonical asset order and normalize."""
        w = np.array([float(weights.get(t, 0.0)) for t in self.tickers])
        return portfolio.normalize_weights(w)

    def list_scenarios(self) -> list[dict]:
        return [
            {k: v for k, v in s.items()} for s in self.scenarios.values()
        ]

    def asset_reference(self) -> list[dict]:
        return self.assets.to_dict(orient="records")

    # ------------------------------------------------------------------ analytics
    def risk_report(self, weights: dict[str, float]) -> dict:
        w = self._weight_vector(weights)
        rc = risk.risk_contributions(w, self.cov)
        return {
            "tickers": self.tickers,
            "weights": {t: float(x) for t, x in zip(self.tickers, w)},
            "portfolio_volatility_weekly": rc.portfolio_volatility,
            "portfolio_volatility_annual": portfolio.annualize_volatility(rc.portfolio_volatility),
            "marginal_contribution": dict(zip(self.tickers, rc.marginal.tolist())),
            "component_contribution": dict(zip(self.tickers, rc.component.tolist())),
            "percentage_contribution": dict(zip(self.tickers, rc.percentage.tolist())),
            "euler_residual": rc.euler_check(),
        }

    def factor_regression(self, weights: dict[str, float]) -> dict:
        w = self._weight_vector(weights)
        port_series = self.asset_returns @ w
        reg = factors.ols_factor_betas(port_series, self.factor_returns, self.factor_names)
        return {"alpha": reg.alpha, "betas": reg.betas, "r_squared": reg.r_squared}

    def stress_test(self, weights: dict[str, float], scenario_id: str,
                    alpha: float = 0.95) -> dict:
        if scenario_id not in self.scenarios:
            raise KeyError(f"Unknown scenario_id '{scenario_id}'")
        scenario = self.scenarios[scenario_id]
        shocks = scenario["shocks"]

        w = self._weight_vector(weights)

        # Scenario pricing.
        asset_scn = factors.scenario_asset_returns(self.assets, shocks)
        portfolio_drawdown = float(w @ asset_scn)
        factor_pnl = factors.factor_pnl_breakdown(self.assets, w, shocks)

        # Risk metrics.
        rc = risk.risk_contributions(w, self.cov)
        sigma_w = rc.portfolio_volatility
        var = portfolio.parametric_var(sigma_w, alpha)
        cvar = portfolio.parametric_cvar(sigma_w, alpha)

        # Mitigation.
        rec = rebalance.recommend_rebalance(w, self.tickers, asset_scn, self.cov)

        # Worst standalone-risk holding (max PCTR).
        pctr = rc.percentage
        worst_idx = int(np.argmax(pctr))

        narrative = commentary.stress_commentary(
            scenario_name=scenario["name"],
            portfolio_drawdown=portfolio_drawdown,
            factor_pnl=factor_pnl,
            worst_holding=self.tickers[worst_idx],
            worst_holding_pctr=float(pctr[worst_idx]),
            worst_holding_weight=float(w[worst_idx]),
            rebalance=rec,
        )

        return {
            "scenario": {"scenario_id": scenario_id, "name": scenario["name"],
                          "description": scenario["description"], "shocks": shocks},
            "weights": {t: float(x) for t, x in zip(self.tickers, w)},
            "portfolio_drawdown": portfolio_drawdown,
            "per_asset_scenario_return": dict(zip(self.tickers, asset_scn.tolist())),
            "per_asset_pnl_contribution": dict(zip(self.tickers, (w * asset_scn).tolist())),
            "factor_pnl_attribution": factor_pnl,
            "volatility_weekly": sigma_w,
            "volatility_annual": portfolio.annualize_volatility(sigma_w),
            "confidence": alpha,
            "var": var,
            "cvar": cvar,
            "risk_contribution": {
                "percentage": dict(zip(self.tickers, pctr.tolist())),
                "component": dict(zip(self.tickers, rc.component.tolist())),
            },
            "rebalance": rec.__dict__,
            "commentary": narrative,
        }

    def reverse_stress(self, weights: dict[str, float], target_loss: float) -> dict:
        w = self._weight_vector(weights)
        res = reverse.reverse_stress(
            weights=w,
            exposure_matrix=self.exposure,
            factor_cov=self.factor_cov,
            target_loss=target_loss,
            factor_names=self.factor_names,
        )
        narrative = commentary.reverse_commentary(
            target_loss=target_loss,
            shocks=res.shocks,
            mahalanobis_distance=res.mahalanobis_distance,
        )
        out = res.__dict__.copy()
        out["commentary"] = narrative
        return out
