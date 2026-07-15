"""Benchmark-relative analytics — the core of Investment & Portfolio Solutions.

IPS builds and monitors multi-asset model portfolios RELATIVE to a strategic benchmark, in
the language of active weights, tracking error, active-risk contribution and factor tilts.
This module adds that lens on top of the absolute-risk engine.

    active weights   a = w - w_bench
    tracking error   TE = sqrt(aᵀ Σ a)                 (annualized)
    active risk ctr  MCTR_i = (Σa)_i / TE, CCTR = a·MCTR, PCTR = CCTR / TE   (Euler)
    factor tilt      t = Bᵀ a                            (active exposure per factor)
"""
from __future__ import annotations

import numpy as np

from .portfolio import annualize_volatility, normalize_weights


def active_analysis(weights: np.ndarray, bench_weights: np.ndarray, cov: np.ndarray,
                    stressed_cov: np.ndarray, exposure: np.ndarray,
                    factor_names: list[str], tickers: list[str]) -> dict:
    """Full benchmark-relative report under both the calm and crisis-regime covariance."""
    w = normalize_weights(weights)
    wb = normalize_weights(bench_weights)
    active = w - wb
    cov = np.asarray(cov, dtype=float)
    scov = np.asarray(stressed_cov, dtype=float)

    def te_and_contrib(sigma: np.ndarray) -> tuple[float, np.ndarray]:
        var = float(active @ sigma @ active)
        te = float(np.sqrt(max(var, 0.0)))
        if te == 0.0:
            return 0.0, np.zeros(len(active))
        mctr = (sigma @ active) / te
        pctr = (active * mctr) / te          # sums to 1 by Euler
        return te, pctr

    te_calm, pctr_calm = te_and_contrib(cov)
    te_crisis, pctr_crisis = te_and_contrib(scov)

    tilt = np.asarray(exposure, dtype=float).T @ active     # active factor exposure

    port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    bench_vol = float(np.sqrt(max(wb @ cov @ wb, 0.0)))

    return {
        "tickers": tickers,
        "active_weights": dict(zip(tickers, active.tolist())),
        "tracking_error_annual_calm": annualize_volatility(te_calm),
        "tracking_error_annual_crisis": annualize_volatility(te_crisis),
        "active_risk_pctr_calm": dict(zip(tickers, pctr_calm.tolist())),
        "active_risk_pctr_crisis": dict(zip(tickers, pctr_crisis.tolist())),
        "factor_tilts": dict(zip(factor_names, tilt.tolist())),
        "portfolio_vol_annual": annualize_volatility(port_vol),
        "benchmark_vol_annual": annualize_volatility(bench_vol),
        "active_share": float(0.5 * np.abs(active).sum()),   # standard active-share measure
    }
