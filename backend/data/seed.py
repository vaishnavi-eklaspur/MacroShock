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
    CRISIS_STAY_PROB,
    CRISIS_VOL_MULTIPLIER,
    CRISIS_WEEK_FRACTION,
    FACTOR_ORDER,
    FACTORS,
    IDIOSYNCRATIC_ANNUAL_VOL,
    MODEL_VERSION,
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


def _markov_regime(rng: np.random.Generator) -> np.ndarray:
    """2-state Markov regime path (0=calm, 1=crisis) with persistence.

    P(crisis->crisis) = CRISIS_STAY_PROB. P(calm->crisis) is solved so the stationary crisis
    probability equals CRISIS_WEEK_FRACTION: pi = (1-a)/((1-a)+(1-b)).
    """
    b = CRISIS_STAY_PROB
    pi = CRISIS_WEEK_FRACTION
    # solve (1-a) from pi = (1-a)/((1-a)+(1-b))
    one_minus_b = 1.0 - b
    one_minus_a = pi * one_minus_b / (1.0 - pi)
    p_calm_to_crisis = one_minus_a
    p_crisis_to_crisis = b

    states = np.zeros(N_WEEKS, dtype=int)
    state = 0
    for t in range(N_WEEKS):
        if state == 0:
            state = 1 if rng.random() < p_calm_to_crisis else 0
        else:
            state = 1 if rng.random() < p_crisis_to_crisis else 0
        states[t] = state
    return states


def _generate_returns() -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(RANDOM_SEED)

    calm_cov = _weekly_cov(CALM_CORRELATIONS, 1.0)
    crisis_cov = _weekly_cov(CRISIS_CORRELATIONS, CRISIS_VOL_MULTIPLIER)

    # Regime path: a 2-state Markov chain so crises PERSIST and cluster (volatility
    # clustering), rather than appearing as isolated i.i.d. spikes. Transition probabilities
    # are set so the crisis regime persists (stay-prob) yet has the target long-run share.
    regime = _markov_regime(rng)

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


def _derive_factor_returns(asset_df: pd.DataFrame) -> pd.DataFrame:
    """Least-squares projection of REAL asset returns onto the exposure matrix -> factor returns.

    Per week a_t = B f_t + e, so f_t = pinv(B) a_t. This yields native-unit factor returns
    (yield/spread changes, index returns) consistent with realized asset behaviour and the
    documented loadings - the same lstsq inversion the backtest uses for implied shocks. It
    avoids scraping unreliable free proxies for credit-spread / liquidity factor levels.
    """
    B = _exposure_matrix()                       # n_assets x n_factors, columns in FACTOR_ORDER
    cols = [a["ticker"] for a in ASSETS]
    A = asset_df[[c for c in cols if c in asset_df.columns]].to_numpy()
    B_sub = B[[i for i, a in enumerate(ASSETS) if a["ticker"] in asset_df.columns], :]
    F = A @ np.linalg.pinv(B_sub).T              # (T x n) @ (n x k) -> T x k
    return pd.DataFrame(F, columns=FACTOR_ORDER, index=asset_df.index)


def build_returns(source: str, csv_path: str | None, start: str, end: str | None,
                  factors_csv: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (asset_returns, factor_returns, provenance). Falls back to synthetic on failure.

    source: 'synthetic' (default, reproducible), 'csv' (a weekly-returns file), or 'yahoo'
    (live download via yfinance). Real sources use INDEPENDENT factor series (Yahoo proxies or
    a --factors-csv) so estimated betas/R² are honest; only if none is available do we fall
    back to a projection of the assets (labelled 'derived-by-projection', which is circular).
    """
    if source == "synthetic":
        adf, fdf, _ = _generate_returns()
        return adf, fdf, {"source": "synthetic", "factors": "independent (latent)",
                          "as_of_start": adf.index[0], "as_of_end": adf.index[-1],
                          "n_weeks": str(len(adf))}
    try:
        from .providers import (
            CsvReturnsProvider,
            YFinanceReturnsProvider,
            download_factor_proxies,
        )
        fdf = None
        if source == "csv":
            if not csv_path:
                raise ValueError("source=csv requires --csv PATH")
            adf = CsvReturnsProvider(csv_path).get_asset_returns()
            if factors_csv:
                fdf = CsvReturnsProvider(factors_csv).get_asset_returns()[FACTOR_ORDER]
        elif source == "yahoo":
            tickers = [a["ticker"] for a in ASSETS]
            adf = YFinanceReturnsProvider(tickers, start=start, end=end).get_asset_returns()
            fdf = download_factor_proxies(start, end)
        else:
            raise ValueError(f"Unknown source '{source}'")

        adf = adf.dropna(how="any")
        if fdf is not None:                       # independent factors: align on common dates
            idx = adf.index.intersection(fdf.index)
            adf, fdf = adf.loc[idx], fdf.loc[idx]
            factor_note = "independent"
        else:                                     # last resort: circular projection
            fdf = _derive_factor_returns(adf)
            factor_note = "derived-by-projection (approximate; pass --factors-csv for a true model)"
        if adf.shape[0] < 60:
            raise ValueError(f"Only {adf.shape[0]} usable weeks from {source}; need >= 60.")
        return adf, fdf, {"source": source, "factors": factor_note,
                          "as_of_start": str(adf.index[0]), "as_of_end": str(adf.index[-1]),
                          "n_weeks": str(len(adf))}
    except Exception as exc:  # network down, bad CSV, missing yfinance -> reproducible fallback
        print(f"[seed] real source '{source}' failed ({exc}); falling back to synthetic.")
        adf, fdf, _ = _generate_returns()
        return adf, fdf, {"source": f"synthetic (fallback from {source})",
                          "factors": "independent (latent)", "as_of_start": adf.index[0],
                          "as_of_end": adf.index[-1], "n_weeks": str(len(adf))}


def seed(db_path: str | None = None, source: str = "synthetic",
         csv_path: str | None = None, start: str = "2010-01-01",
         end: str | None = None, factors_csv: str | None = None) -> str:
    conn = snowflake_mock.connect(database=db_path)
    db_file = conn._db_path  # noqa: SLF001

    conn.executescript(SCHEMA_PATH.read_text())
    cur = conn.cursor()

    for table in ("realized_crisis_returns", "scenario_shocks", "scenarios",
                  "factor_returns", "asset_returns", "factors", "assets", "dataset_meta"):
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

    adf, fdf, provenance = build_returns(source, csv_path, start, end, factors_csv)
    for date, row in adf.iterrows():
        for ticker, ret in row.items():
            cur.execute("INSERT INTO asset_returns (ticker, obs_date, weekly_return) VALUES (?,?,?)",
                        (ticker, str(date), float(ret)))
    for date, row in fdf.iterrows():
        for factor_name, ret in row.items():
            cur.execute("INSERT INTO factor_returns (factor_name, obs_date, weekly_return) VALUES (?,?,?)",
                        (factor_name, str(date), float(ret)))

    provenance["model_version"] = MODEL_VERSION
    for k, v in provenance.items():
        cur.execute("INSERT INTO dataset_meta (key, value) VALUES (?,?)", (k, str(v)))

    conn.commit()
    conn.close()
    return db_file


if __name__ == "__main__":
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Seed the MacroShock database.")
    ap.add_argument("--source", choices=["synthetic", "csv", "yahoo"],
                    default=os.getenv("MACROSHOCK_SOURCE", "synthetic"),
                    help="Return-history source (default: synthetic, reproducible; env MACROSHOCK_SOURCE).")
    ap.add_argument("--csv", dest="csv_path", default=os.getenv("MACROSHOCK_CSV"),
                    help="Path to a weekly asset-returns CSV (env MACROSHOCK_CSV).")
    ap.add_argument("--factors-csv", dest="factors_csv", default=os.getenv("MACROSHOCK_FACTORS_CSV"),
                    help="Independent factor-returns CSV, else projected (env MACROSHOCK_FACTORS_CSV).")
    ap.add_argument("--start", default=os.getenv("MACROSHOCK_START", "2010-01-01"),
                    help="Start date for --source yahoo (env MACROSHOCK_START).")
    ap.add_argument("--end", default=None, help="End date for --source yahoo.")
    args = ap.parse_args()

    path = seed(source=args.source, csv_path=args.csv_path, start=args.start, end=args.end,
                factors_csv=args.factors_csv)
    print(f"Seeded MacroShock database at: {path}")
    print(f"  assets={len(ASSETS)}  factors={len(FACTORS)}  scenarios={len(SCENARIOS)}")
    print(f"  realized-return scenarios={len(REALIZED_CRISIS_RETURNS)}")
