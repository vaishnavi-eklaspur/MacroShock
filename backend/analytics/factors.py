"""Factor model: OLS factor betas and factor-shock scenario pricing.

Formulas in docs/METHODOLOGY.md sections 5 and 6.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Canonical factor order used across the engine.
FACTOR_ORDER = ["Equity", "Rates", "Credit", "Commodity"]


@dataclass
class FactorRegression:
    alpha: float
    betas: dict[str, float]
    r_squared: float


def ols_factor_betas(y: np.ndarray, factor_returns: np.ndarray,
                     factor_names: list[str] | None = None) -> FactorRegression:
    """Multivariate OLS of a return series y on factor return columns.

    Solves the normal equations beta_hat = (Xᵀ X)⁻¹ Xᵀ y with an intercept column,
    via a numerically stable least-squares solve (mathematically equivalent).
    """
    y = np.asarray(y, dtype=float)
    F = np.asarray(factor_returns, dtype=float)
    if F.ndim == 1:
        F = F.reshape(-1, 1)
    names = factor_names or FACTOR_ORDER[: F.shape[1]]

    X = np.column_stack([np.ones(len(y)), F])          # intercept + factors
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    alpha, betas = float(coef[0]), coef[1:]

    resid = y - X @ coef
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return FactorRegression(
        alpha=alpha,
        betas={name: float(b) for name, b in zip(names, betas)},
        r_squared=float(r2),
    )


def exposure_matrix(assets: pd.DataFrame) -> np.ndarray:
    """Linear factor-exposure matrix B (n_assets x n_factors), columns in FACTOR_ORDER.

    Equity    -> equity_beta
    Rates     -> -eff_duration       (bond price sensitivity to yield changes)
    Credit    -> -spread_duration
    Commodity -> commodity_beta
    """
    B = np.zeros((len(assets), len(FACTOR_ORDER)))
    B[:, 0] = assets["equity_beta"].to_numpy()
    B[:, 1] = -assets["eff_duration"].to_numpy()
    B[:, 2] = -assets["spread_duration"].to_numpy()
    B[:, 3] = assets["commodity_beta"].to_numpy()
    return B


def shocks_to_vector(shocks: dict[str, float]) -> np.ndarray:
    """Convert a {factor_name: shock} mapping to a vector in FACTOR_ORDER."""
    return np.array([float(shocks.get(f, 0.0)) for f in FACTOR_ORDER])


def scenario_asset_returns(assets: pd.DataFrame, shocks: dict[str, float]) -> np.ndarray:
    """Per-asset return under a factor-shock scenario.

    r_i = beta_eq*eq + (-D_i*dy + 0.5*C_i*dy^2) + (-SD_i*dspread) + beta_comm*comm

    The convexity term (0.5*C*dy^2) makes bond pricing accurate under large yield moves.
    """
    eq = float(shocks.get("Equity", 0.0))
    dy = float(shocks.get("Rates", 0.0))
    dspread = float(shocks.get("Credit", 0.0))
    comm = float(shocks.get("Commodity", 0.0))

    equity_pnl = assets["equity_beta"].to_numpy() * eq
    rates_pnl = -assets["eff_duration"].to_numpy() * dy + 0.5 * assets["convexity"].to_numpy() * dy**2
    credit_pnl = -assets["spread_duration"].to_numpy() * dspread
    commodity_pnl = assets["commodity_beta"].to_numpy() * comm
    return equity_pnl + rates_pnl + credit_pnl + commodity_pnl


def factor_pnl_breakdown(assets: pd.DataFrame, weights: np.ndarray,
                         shocks: dict[str, float]) -> dict[str, float]:
    """Portfolio P&L attributed to each factor (sums to total scenario return)."""
    w = np.asarray(weights, dtype=float)
    eq = float(shocks.get("Equity", 0.0))
    dy = float(shocks.get("Rates", 0.0))
    dspread = float(shocks.get("Credit", 0.0))
    comm = float(shocks.get("Commodity", 0.0))

    return {
        "Equity": float(w @ (assets["equity_beta"].to_numpy() * eq)),
        "Rates": float(w @ (-assets["eff_duration"].to_numpy() * dy
                            + 0.5 * assets["convexity"].to_numpy() * dy**2)),
        "Credit": float(w @ (-assets["spread_duration"].to_numpy() * dspread)),
        "Commodity": float(w @ (assets["commodity_beta"].to_numpy() * comm)),
    }


def factor_weekly_covariance(factor_returns: np.ndarray) -> np.ndarray:
    """Sample covariance of the factor return series (n_factors x n_factors)."""
    return np.cov(np.asarray(factor_returns, dtype=float), rowvar=False, ddof=1)
