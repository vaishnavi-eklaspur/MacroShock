"""Build and populate the MacroShock SQLite database.

Run:  python -m data.seed   (from the backend/ directory)

Generates a weekly history calibrated to the documented annualized volatilities and
cross-factor correlations in reference.py. Asset returns are constructed from the factor
model (asset = exposures . factor_returns + idiosyncratic noise) so that:
  * the OLS factor regression recovers the specified betas/durations, and
  * the covariance/risk machinery operates on realistic, internally-consistent data.

A fixed random seed makes the dataset fully reproducible. Scenario shocks are the
calibrated crisis magnitudes (not generated) - see docs/METHODOLOGY.md sec 6.3.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import snowflake_mock
from .reference import (
    ASSETS,
    FACTOR_CORRELATIONS,
    FACTOR_ORDER,
    FACTORS,
    IDIOSYNCRATIC_ANNUAL_VOL,
    N_WEEKS,
    RANDOM_SEED,
    SCENARIOS,
)

WEEKS_PER_YEAR = 52
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _exposure_matrix() -> np.ndarray:
    """n_assets x n_factors linear exposure matrix B (order: ASSETS x FACTOR_ORDER)."""
    fidx = {f: i for i, f in enumerate(FACTOR_ORDER)}
    B = np.zeros((len(ASSETS), len(FACTOR_ORDER)))
    for i, a in enumerate(ASSETS):
        B[i, fidx["Equity"]] = a["equity_beta"]
        B[i, fidx["Rates"]] = -a["eff_duration"]        # price change per +1 unit of yield
        B[i, fidx["Credit"]] = -a["spread_duration"]    # price change per +1 unit of spread
        B[i, fidx["Commodity"]] = a["commodity_beta"]
    return B


def _factor_weekly_cov() -> np.ndarray:
    """Weekly factor covariance from annualized vols + correlation matrix."""
    annual_vol = np.array([f["annual_vol"] for f in FACTORS])
    weekly_vol = annual_vol / np.sqrt(WEEKS_PER_YEAR)
    corr = np.array(FACTOR_CORRELATIONS)
    D = np.diag(weekly_vol)
    return D @ corr @ D


def _generate_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(RANDOM_SEED)

    # Weekly factor returns ~ N(0, Sigma_F). (Zero mean: stress is about volatility.)
    cov = _factor_weekly_cov()
    L = np.linalg.cholesky(cov)
    z = rng.standard_normal((N_WEEKS, len(FACTOR_ORDER)))
    factor_returns = z @ L.T  # N_WEEKS x n_factors

    # Asset returns from the factor model + idiosyncratic noise.
    B = _exposure_matrix()                     # n_assets x n_factors
    systematic = factor_returns @ B.T          # N_WEEKS x n_assets
    idio_weekly_vol = IDIOSYNCRATIC_ANNUAL_VOL / np.sqrt(WEEKS_PER_YEAR)
    idio = rng.standard_normal((N_WEEKS, len(ASSETS))) * idio_weekly_vol
    asset_returns = systematic + idio

    dates = pd.date_range(end="2026-07-10", periods=N_WEEKS, freq="W-FRI").strftime("%Y-%m-%d")
    fdf = pd.DataFrame(factor_returns, columns=FACTOR_ORDER, index=dates)
    adf = pd.DataFrame(asset_returns, columns=[a["ticker"] for a in ASSETS], index=dates)
    return adf, fdf


def seed(db_path: str | None = None) -> str:
    conn = snowflake_mock.connect(database=db_path)
    db_file = conn._db_path  # noqa: SLF001 - internal path for logging

    # (Re)create schema.
    conn.executescript(SCHEMA_PATH.read_text())
    cur = conn.cursor()

    # Clear existing rows (idempotent reseed).
    for table in ("scenario_shocks", "scenarios", "factor_returns",
                  "asset_returns", "factors", "assets"):
        cur.execute(f"DELETE FROM {table}")

    # Reference: assets.
    for a in ASSETS:
        cur.execute(
            "INSERT INTO assets (ticker, name, asset_class, equity_beta, eff_duration, "
            "spread_duration, commodity_beta, convexity, display_order) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (a["ticker"], a["name"], a["asset_class"], a["equity_beta"], a["eff_duration"],
             a["spread_duration"], a["commodity_beta"], a["convexity"], a["display_order"]),
        )

    # Reference: factors.
    for f in FACTORS:
        cur.execute(
            "INSERT INTO factors (name, description, unit, annual_vol) VALUES (?,?,?,?)",
            (f["name"], f["description"], f["unit"], f["annual_vol"]),
        )

    # Reference: scenarios + shocks.
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

    # Facts: generated returns.
    adf, fdf = _generate_returns()
    for date, row in adf.iterrows():
        for ticker, ret in row.items():
            cur.execute(
                "INSERT INTO asset_returns (ticker, obs_date, weekly_return) VALUES (?,?,?)",
                (ticker, date, float(ret)),
            )
    for date, row in fdf.iterrows():
        for factor_name, ret in row.items():
            cur.execute(
                "INSERT INTO factor_returns (factor_name, obs_date, weekly_return) VALUES (?,?,?)",
                (factor_name, date, float(ret)),
            )

    conn.commit()
    conn.close()
    return db_file


if __name__ == "__main__":
    path = seed()
    print(f"Seeded MacroShock database at: {path}")
    print(f"  assets={len(ASSETS)}  factors={len(FACTORS)}  scenarios={len(SCENARIOS)}  weeks={N_WEEKS}")
