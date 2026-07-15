"""Build and populate the MacroShock SQLite database.

Run:  python -m data.seed   (from the backend/ directory)

Design decisions that make the dataset defensible under scrutiny:
  * Two-regime generation (calm + crisis) with REGIME-DEPENDENT correlations, so
    cross-asset correlations rise in stress - the contagion effect single-regime models
    miss. The analytics estimate a *stressed* covariance conditional on the crisis regime.
  * Student-t factor innovations (fat tails), fatter in the crisis regime, so parametric
    Gaussian risk measures are demonstrably too optimistic vs. historical/EVT measures.
  * Idiosyncratic noise sized so the factor regression R^2 is realistic (~0.7-0.85), NOT
    the ~0.99 you get when asset returns are a noiseless function of the factors.
  * Realized crisis returns are loaded as INDEPENDENT ground truth for backtesting.

A fixed seed makes everything reproducible.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import snowflake_mock
from .reference import (
    ASSETS,
    CALM_CORRELATIONS,
    CRISIS_CORRELATIONS,
    CRISIS_VOL_MULTIPLIER,
    CRISIS_WEEK_FRACTION,
    FACTOR_ORDER,
    FACTORS,
    IDIOSYNCRATIC_ANNUAL_VOL,
    N_WEEKS,
    RANDOM_SEED,
    REALIZED_CRISIS_RETURNS,
    SCENARIOS,
    STUDENT_T_DOF_CALM,
    STUDENT_T_DOF_CRISIS,
)

WEEKS_PER_YEAR = 52
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _exposure_matrix() -> np.ndarray:
    """n_assets x n_factors linear exposure matrix B (ASSETS x FACTOR_ORDER)."""
    fidx = {f: i for i, f in enumerate(FACTOR_ORDER)}
    B = np.zeros((len(ASSETS), len(FACTOR_ORDER)))
    for i, a in enumerate(ASSETS):
        B[i, fidx["Equity"]] = a["equity_beta"]
        B[i, fidx["Rates"]] = -a["eff_duration"]
        B[i, fidx["Credit"]] = -a["spread_duration"]
        B[i, fidx["Commodity"]] = a["commodity_beta"]
        B[i, fidx["Liquidity"]] = a["liquidity_beta"]
        B[i, fidx["FX"]] = a["fx_beta"]
    return B


def nearest_psd(matrix: np.ndarray) -> np.ndarray:
    """Nearest positive-semidefinite matrix via eigenvalue clipping (then re-symmetrized).

    Guarantees the hand-specified crisis correlation matrix is usable for Cholesky even if
    the elevated off-diagonals push it slightly indefinite.
    """
    A = (matrix + matrix.T) / 2.0
    vals, vecs = np.linalg.eigh(A)
    vals = np.clip(vals, 1e-8, None)
    psd = vecs @ np.diag(vals) @ vecs.T
    # renormalize to unit diagonal (it is a correlation matrix)
    d = np.sqrt(np.diag(psd))
    psd = psd / np.outer(d, d)
    return (psd + psd.T) / 2.0


def _weekly_cov(correlations: list[list[float]], vol_multiplier: float = 1.0) -> np.ndarray:
    annual_vol = np.array([f["annual_vol"] for f in FACTORS]) * vol_multiplier
    weekly_vol = annual_vol / np.sqrt(WEEKS_PER_YEAR)
    corr = nearest_psd(np.array(correlations))
    D = np.diag(weekly_vol)
    return D @ corr @ D


def _multivariate_t(rng: np.random.Generator, cov: np.ndarray, dof: float, n: int) -> np.ndarray:
    """n draws from a multivariate Student-t scaled so its covariance equals `cov`.

    x = L z / sqrt(w),  w ~ chi2(dof)/dof.  Raw t-cov = Sigma*dof/(dof-2); we pre-scale
    Sigma by (dof-2)/dof so the realized covariance matches the target `cov`.
    """
    k = cov.shape[0]
    scaled = cov * (dof - 2.0) / dof
    L = np.linalg.cholesky(nearest_psd(scaled) if np.min(np.linalg.eigvalsh(scaled)) <= 0 else scaled)
    z = rng.standard_normal((n, k))
    w = rng.chisquare(dof, size=n) / dof
    return (z @ L.T) / np.sqrt(w)[:, None]


def _generate_returns() -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(RANDOM_SEED)

    calm_cov = _weekly_cov(CALM_CORRELATIONS, 1.0)
    crisis_cov = _weekly_cov(CRISIS_CORRELATIONS, CRISIS_VOL_MULTIPLIER)

    # Regime path: independent Bernoulli per week (simple, transparent). 1 == crisis.
    regime = (rng.random(N_WEEKS) < CRISIS_WEEK_FRACTION).astype(int)

    factor_returns = np.zeros((N_WEEKS, len(FACTOR_ORDER)))
    calm_idx = np.where(regime == 0)[0]
    crisis_idx = np.where(regime == 1)[0]
    if len(calm_idx):
        factor_returns[calm_idx] = _multivariate_t(rng, calm_cov, STUDENT_T_DOF_CALM, len(calm_idx))
    if len(crisis_idx):
        factor_returns[crisis_idx] = _multivariate_t(rng, crisis_cov, STUDENT_T_DOF_CRISIS, len(crisis_idx))

    # Asset returns = factor exposures . factor returns + idiosyncratic noise.
    B = _exposure_matrix()
    systematic = factor_returns @ B.T
    idio_weekly_vol = IDIOSYNCRATIC_ANNUAL_VOL / np.sqrt(WEEKS_PER_YEAR)
    idio = rng.standard_normal((N_WEEKS, len(ASSETS))) * idio_weekly_vol
    asset_returns = systematic + idio

    dates = pd.date_range(end="2026-07-10", periods=N_WEEKS, freq="W-FRI").strftime("%Y-%m-%d")
    fdf = pd.DataFrame(factor_returns, columns=FACTOR_ORDER, index=dates)
    adf = pd.DataFrame(asset_returns, columns=[a["ticker"] for a in ASSETS], index=dates)
    return adf, fdf, regime


def seed(db_path: str | None = None) -> str:
    conn = snowflake_mock.connect(database=db_path)
    db_file = conn._db_path  # noqa: SLF001

    conn.executescript(SCHEMA_PATH.read_text())
    cur = conn.cursor()

    for table in ("realized_crisis_returns", "scenario_shocks", "scenarios",
                  "factor_returns", "asset_returns", "factors", "assets"):
        cur.execute(f"DELETE FROM {table}")

    for a in ASSETS:
        cur.execute(
            "INSERT INTO assets (ticker, name, asset_class, equity_beta, eff_duration, "
            "spread_duration, commodity_beta, liquidity_beta, fx_beta, convexity, display_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (a["ticker"], a["name"], a["asset_class"], a["equity_beta"], a["eff_duration"],
             a["spread_duration"], a["commodity_beta"], a["liquidity_beta"], a["fx_beta"],
             a["convexity"], a["display_order"]),
        )

    for f in FACTORS:
        cur.execute(
            "INSERT INTO factors (name, description, unit, annual_vol) VALUES (?,?,?,?)",
            (f["name"], f["description"], f["unit"], f["annual_vol"]),
        )

    for s in SCENARIOS:
        cur.execute(
            "INSERT INTO scenarios (scenario_id, name, description, is_historical, display_order) "
            "VALUES (?,?,?,?,?)",
            (s["scenario_id"], s["name"], s["description"], s["is_historical"], s["display_order"]),
        )
        for factor_name, shock in s["shocks"].items():
            cur.execute(
                "INSERT INTO scenario_shocks (scenario_id, factor_name, shock) VALUES (?,?,?)",
                (s["scenario_id"], factor_name, shock),
            )

    for scenario_id, rets in REALIZED_CRISIS_RETURNS.items():
        for ticker, ret in rets.items():
            cur.execute(
                "INSERT INTO realized_crisis_returns (scenario_id, ticker, realized_return) "
                "VALUES (?,?,?)",
                (scenario_id, ticker, ret),
            )

    adf, fdf, regime = _generate_returns()
    for date, row in adf.iterrows():
        for ticker, ret in row.items():
            cur.execute("INSERT INTO asset_returns (ticker, obs_date, weekly_return) VALUES (?,?,?)",
                        (ticker, date, float(ret)))
    for date, row in fdf.iterrows():
        for factor_name, ret in row.items():
            cur.execute("INSERT INTO factor_returns (factor_name, obs_date, weekly_return) VALUES (?,?,?)",
                        (factor_name, date, float(ret)))

    conn.commit()
    conn.close()
    return db_file


if __name__ == "__main__":
    path = seed()
    print(f"Seeded MacroShock database at: {path}")
    print(f"  assets={len(ASSETS)}  factors={len(FACTORS)}  scenarios={len(SCENARIOS)}  weeks={N_WEEKS}")
    print(f"  crisis-regime weeks ~ {int(CRISIS_WEEK_FRACTION*N_WEEKS)}  |  realized-return scenarios="
          f"{len(REALIZED_CRISIS_RETURNS)}")
