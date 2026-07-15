"""Factor model: OLS factor betas (with diagnostics) and factor-shock scenario pricing.

Formulas in docs/METHODOLOGY.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Canonical factor order (single source of truth is the data layer).
from data.reference import FACTOR_ORDER  # noqa: E402


@dataclass
class FactorRegression:
    alpha: float
    betas: dict[str, float]
    r_squared: float
    adj_r_squared: float
    t_stats: dict[str, float] = field(default_factory=dict)
    std_errors: dict[str, float] = field(default_factory=dict)
    alpha_t_stat: float = 0.0


def ols_factor_betas(y: np.ndarray, factor_returns: np.ndarray,
                     factor_names: list[str] | None = None) -> FactorRegression:
    """Multivariate OLS of a return series y on factor return columns, with diagnostics.

    beta_hat = (XᵀX)⁻¹ Xᵀy (via stable lstsq). Standard errors from the classical OLS
    covariance s² (XᵀX)⁻¹, and t-stats = beta / se. R² and adjusted-R² reported so a
    reviewer can see how much variance the factors actually explain (a realistic model is
    well below 1.0).
    """
    y = np.asarray(y, dtype=float)
    F = np.asarray(factor_returns, dtype=float)
    if F.ndim == 1:
        F = F.reshape(-1, 1)
    names = factor_names or FACTOR_ORDER[: F.shape[1]]

    X = np.column_stack([np.ones(len(y)), F])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = X.shape
    dof = max(n - k, 1)
    s2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(s2 * XtX_inv), 0.0))
    t_stat = np.divide(coef, se, out=np.zeros_like(coef), where=se > 0)

    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if ss_tot > 0 else 0.0

    return FactorRegression(
        alpha=float(coef[0]),
        betas={name: float(b) for name, b in zip(names, coef[1:])},
        r_squared=float(r2),
        adj_r_squared=float(adj_r2),
        t_stats={name: float(t) for name, t in zip(names, t_stat[1:])},
        std_errors={name: float(s) for name, s in zip(names, se[1:])},
        alpha_t_stat=float(t_stat[0]),
    )


def exposure_matrix(assets: pd.DataFrame) -> np.ndarray:
    """Linear factor-exposure matrix B (n_assets x n_factors), columns in FACTOR_ORDER.

    Equity->equity_beta, Rates->-eff_duration, Credit->-spread_duration,
    Commodity->commodity_beta, Liquidity->liquidity_beta, FX->fx_beta.
    """
    B = np.zeros((len(assets), len(FACTOR_ORDER)))
    B[:, 0] = assets["equity_beta"].to_numpy()
    B[:, 1] = -assets["eff_duration"].to_numpy()
    B[:, 2] = -assets["spread_duration"].to_numpy()
    B[:, 3] = assets["commodity_beta"].to_numpy()
    B[:, 4] = assets["liquidity_beta"].to_numpy()
    B[:, 5] = assets["fx_beta"].to_numpy()
    return B


def shocks_to_vector(shocks: dict[str, float]) -> np.ndarray:
    return np.array([float(shocks.get(f, 0.0)) for f in FACTOR_ORDER])


def scenario_asset_returns(assets: pd.DataFrame, shocks: dict[str, float]) -> np.ndarray:
    """Per-asset return under a factor-shock scenario.

    r_i = beta_eq*eq + (-D_i*dy + 0.5*C_i*dy^2) + (-SD_i*dspread)
          + beta_comm*comm + beta_liq*liq + beta_fx*fx
    """
    eq = float(shocks.get("Equity", 0.0))
    dy = float(shocks.get("Rates", 0.0))
    dspread = float(shocks.get("Credit", 0.0))
    comm = float(shocks.get("Commodity", 0.0))
    liq = float(shocks.get("Liquidity", 0.0))
    fx = float(shocks.get("FX", 0.0))

    equity_pnl = assets["equity_beta"].to_numpy() * eq
    rates_pnl = -assets["eff_duration"].to_numpy() * dy + 0.5 * assets["convexity"].to_numpy() * dy**2
    credit_pnl = -assets["spread_duration"].to_numpy() * dspread
    commodity_pnl = assets["commodity_beta"].to_numpy() * comm
    liquidity_pnl = assets["liquidity_beta"].to_numpy() * liq
    fx_pnl = assets["fx_beta"].to_numpy() * fx
    return equity_pnl + rates_pnl + credit_pnl + commodity_pnl + liquidity_pnl + fx_pnl


def factor_pnl_breakdown(assets: pd.DataFrame, weights: np.ndarray,
                         shocks: dict[str, float]) -> dict[str, float]:
    """Portfolio P&L attributed to each factor (sums to total scenario return)."""
    w = np.asarray(weights, dtype=float)
    eq = float(shocks.get("Equity", 0.0))
    dy = float(shocks.get("Rates", 0.0))
    dspread = float(shocks.get("Credit", 0.0))
    comm = float(shocks.get("Commodity", 0.0))
    liq = float(shocks.get("Liquidity", 0.0))
    fx = float(shocks.get("FX", 0.0))

    return {
        "Equity": float(w @ (assets["equity_beta"].to_numpy() * eq)),
        "Rates": float(w @ (-assets["eff_duration"].to_numpy() * dy
                            + 0.5 * assets["convexity"].to_numpy() * dy**2)),
        "Credit": float(w @ (-assets["spread_duration"].to_numpy() * dspread)),
        "Commodity": float(w @ (assets["commodity_beta"].to_numpy() * comm)),
        "Liquidity": float(w @ (assets["liquidity_beta"].to_numpy() * liq)),
        "FX": float(w @ (assets["fx_beta"].to_numpy() * fx)),
    }


def factor_weekly_covariance(factor_returns: np.ndarray) -> np.ndarray:
    return np.cov(np.asarray(factor_returns, dtype=float), rowvar=False, ddof=1)
