"""Canonical reference data for MacroShock.

Single source of truth for the asset universe, macro factors, factor sensitivities,
calibrated stress scenarios, and realized crisis returns (for backtesting). The seed
script writes these into SQLite; the analytics layer never hard-codes them (it reads from
the data layer). Keeping them here makes every assumption auditable and easy to revise.

All numbers and their provenance are documented in docs/METHODOLOGY.md.
"""
from __future__ import annotations

# Bumped whenever the model or reference data changes; used to version the cache so a
# model change can never serve stale (now-wrong) cached numbers.
MODEL_VERSION = "2.0.0"

# --- Macro factors -----------------------------------------------------------------
# unit:
#   'return'        -> total-return shock (equity index, commodity, liquidity, FX)
#   'yield_change'  -> change in yield, decimal (+0.02 == +200bps)
#   'spread_change' -> change in credit spread, decimal (+0.04 == +400bps)
# annual_vol is the annualized volatility used to build the (calm-regime) factor covariance.
FACTORS: list[dict] = [
    {"name": "Equity",    "description": "Broad equity market total return",         "unit": "return",        "annual_vol": 0.16},
    {"name": "Rates",     "description": "Change in the 10y Treasury yield",          "unit": "yield_change",  "annual_vol": 0.010},
    {"name": "Credit",    "description": "Change in investment-grade credit spread",  "unit": "spread_change", "annual_vol": 0.008},
    {"name": "Commodity", "description": "Broad commodity index total return",        "unit": "return",        "annual_vol": 0.20},
    {"name": "Liquidity", "description": "Funding/market-liquidity factor return (down = stress)", "unit": "return", "annual_vol": 0.06},
    {"name": "FX",        "description": "Trade-weighted USD return (up = USD strength)",          "unit": "return", "annual_vol": 0.08},
]

FACTOR_ORDER = [f["name"] for f in FACTORS]

# --- Regime-dependent factor correlations -------------------------------------------
# Order: [Equity, Rates, Credit, Commodity, Liquidity, FX]
# CALM regime: normal-times co-movement.
CALM_CORRELATIONS: list[list[float]] = [
    [ 1.00,  0.20, -0.45,  0.40,  0.35, -0.20],  # Equity
    [ 0.20,  1.00, -0.25,  0.10,  0.15,  0.05],  # Rates (change in yield)
    [-0.45, -0.25,  1.00, -0.25, -0.55,  0.15],  # Credit (change in spread)
    [ 0.40,  0.10, -0.25,  1.00,  0.30, -0.35],  # Commodity
    [ 0.35,  0.15, -0.55,  0.30,  1.00, -0.25],  # Liquidity (return; down = stress)
    [-0.20,  0.05,  0.15, -0.35, -0.25,  1.00],  # FX (USD)
]
# CRISIS regime: correlations amplify toward the risk-off cluster (contagion). This is the
# empirical fact single-regime models miss; the seed generates from BOTH regimes and the
# analytics estimate a stressed covariance conditional on the crisis regime.
CRISIS_CORRELATIONS: list[list[float]] = [
    [ 1.00,  0.35, -0.75,  0.65,  0.65, -0.45],  # Equity
    [ 0.35,  1.00, -0.40,  0.20,  0.30,  0.15],  # Rates
    [-0.75, -0.40,  1.00, -0.45, -0.80,  0.35],  # Credit
    [ 0.65,  0.20, -0.45,  1.00,  0.55, -0.55],  # Commodity
    [ 0.65,  0.30, -0.80,  0.55,  1.00, -0.45],  # Liquidity
    [-0.45,  0.15,  0.35, -0.55, -0.45,  1.00],  # FX
]

# --- Asset universe & factor sensitivities ------------------------------------------
# exposure mapping (methodology):
#   Equity    exposure = equity_beta
#   Rates     exposure = -eff_duration        (price ~ -D*dy + 0.5*C*dy^2)
#   Credit    exposure = -spread_duration
#   Commodity exposure = commodity_beta
#   Liquidity exposure = liquidity_beta        (loading on the liquidity factor return)
#   FX        exposure = fx_beta               (sensitivity to USD strength)
#
# Provenance: durations reflect published effective/spread durations for these fund
# categories (as-of 2024); equity/commodity/liquidity/FX betas are calibrated to long-run
# observed sensitivities. GLD is modelled as a safe-haven / real-rates asset (small
# commodity loading, negative FX loading), NOT a pure commodity - see METHODOLOGY.
ASSETS: list[dict] = [
    {"ticker": "SPY", "name": "S&P 500 ETF",                    "asset_class": "Equity",
     "equity_beta": 1.00, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.10,
     "liquidity_beta": 0.30, "fx_beta": -0.10, "convexity": 0.0,  "display_order": 1},
    {"ticker": "IEF", "name": "7-10y US Treasury ETF",          "asset_class": "Fixed Income - Rates",
     "equity_beta": -0.05, "eff_duration": 7.5, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": -0.10, "fx_beta": 0.05, "convexity": 75.0, "display_order": 2},
    {"ticker": "LQD", "name": "Investment-Grade Corp Bond ETF", "asset_class": "Fixed Income - Credit",
     "equity_beta": 0.20, "eff_duration": 8.4, "spread_duration": 8.4, "commodity_beta": 0.00,
     "liquidity_beta": 0.80, "fx_beta": -0.05, "convexity": 95.0, "display_order": 3},
    {"ticker": "GLD", "name": "Gold (safe haven / real rates)", "asset_class": "Precious Metal - Safe Haven",
     "equity_beta": -0.10, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.25,
     "liquidity_beta": 0.20, "fx_beta": -0.40, "convexity": 0.0,  "display_order": 4},
    {"ticker": "DBC", "name": "Broad Commodity Index",          "asset_class": "Commodity",
     "equity_beta": 0.35, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 1.00,
     "liquidity_beta": 0.40, "fx_beta": -0.30, "convexity": 0.0,  "display_order": 5},
]

ASSET_ORDER = [a["ticker"] for a in ASSETS]

# --- Calibrated stress scenarios ----------------------------------------------------
# Shocks in native factor units. Magnitudes calibrated to documented crisis moves.
SCENARIOS: list[dict] = [
    {
        "scenario_id": "GFC_2008", "name": "2008 Global Financial Crisis (acute)",
        "description": "Sep 2008-Mar 2009: equity collapse, flight to quality, IG spreads blow out, "
                       "funding freeze, USD haven bid, oil crash.",
        "is_historical": 1, "display_order": 1,
        "shocks": {"Equity": -0.45, "Rates": -0.0150, "Credit": 0.0400,
                    "Commodity": -0.50, "Liquidity": -0.15, "FX": 0.10},
    },
    {
        "scenario_id": "COVID_2020", "name": "2020 COVID Liquidity Freeze",
        "description": "Feb 19-Mar 23 2020: S&P -33.9%, record-low yields, spreads +200bps, a severe "
                       "dash-for-cash liquidity freeze, USD spike, oil crash.",
        "is_historical": 1, "display_order": 2,
        "shocks": {"Equity": -0.34, "Rates": -0.0120, "Credit": 0.0200,
                    "Commodity": -0.40, "Liquidity": -0.25, "FX": 0.08},
    },
    {
        "scenario_id": "INFLATION_2026", "name": "Synthetic 2026 Inflation Spike",
        "description": "Forward-looking: yields rise sharply, bonds fall, credit widens modestly, "
                       "real assets rally, mild funding stress, softer USD.",
        "is_historical": 0, "display_order": 3,
        "shocks": {"Equity": -0.15, "Rates": 0.0200, "Credit": 0.0150,
                    "Commodity": 0.30, "Liquidity": -0.02, "FX": -0.05},
    },
]

# --- Realized crisis returns (backtest ground truth) --------------------------------
# Representative realized total returns over each crisis window, from documented market
# history. These are INDEPENDENT of the factor model (not generated from exposures), so
# comparing model-predicted vs. these realized figures is a genuine out-of-sample check,
# not a self-fulfilling one. Synthetic scenarios have no realized data and are excluded.
REALIZED_CRISIS_RETURNS: dict[str, dict[str, float]] = {
    "GFC_2008":   {"SPY": -0.46, "IEF": 0.15, "LQD": -0.05, "GLD": 0.05, "DBC": -0.50},
    "COVID_2020": {"SPY": -0.34, "IEF": 0.06, "LQD": -0.12, "GLD": -0.02, "DBC": -0.38},
}

# Default illustrative portfolio (weights sum to 1.0).
DEFAULT_WEIGHTS: dict[str, float] = {"SPY": 0.40, "IEF": 0.20, "LQD": 0.20, "GLD": 0.10, "DBC": 0.10}

# --- History generation parameters --------------------------------------------------
N_WEEKS = 520                    # ~10 years of weekly observations
RANDOM_SEED = 20260715           # fixed for reproducibility
IDIOSYNCRATIC_ANNUAL_VOL = 0.06  # asset-specific noise -> realistic factor R^2 (~0.7-0.85)
CRISIS_WEEK_FRACTION = 0.12      # share of weeks drawn from the crisis regime
CRISIS_VOL_MULTIPLIER = 2.5      # factor vol amplification in the crisis regime
STUDENT_T_DOF_CALM = 8.0         # fat tails even in calm times
STUDENT_T_DOF_CRISIS = 4.0       # fatter tails in crisis
