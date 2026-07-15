"""Canonical reference data for MacroShock.

Single source of truth for the asset universe, macro factors, factor sensitivities
and calibrated stress scenarios. The seed script writes these into SQLite; the analytics
layer never hard-codes them (it reads from the data layer). Keeping them here makes the
assumptions auditable and easy to revise.

All numbers are documented in docs/METHODOLOGY.md (sections 6.2 and 6.3).
"""
from __future__ import annotations

# --- Macro factors -----------------------------------------------------------------
# unit:
#   'return'        -> a total-return shock (e.g. equity index -0.34)
#   'yield_change'  -> change in yield, decimal (e.g. +0.02 == +200bps)
#   'spread_change' -> change in credit spread, decimal (e.g. +0.04 == +400bps)
# annual_vol is the annualized volatility used to build the factor covariance matrix.
FACTORS: list[dict] = [
    {"name": "Equity",    "description": "Broad equity market total return",      "unit": "return",        "annual_vol": 0.16},
    {"name": "Rates",     "description": "Change in the 10y Treasury yield",       "unit": "yield_change",  "annual_vol": 0.010},
    {"name": "Credit",    "description": "Change in investment-grade credit spread","unit": "spread_change", "annual_vol": 0.008},
    {"name": "Commodity", "description": "Broad commodity index total return",     "unit": "return",        "annual_vol": 0.20},
]

# Correlation matrix between factors, ordered as FACTORS above:
# [Equity, Rates(dy), Credit(dspread), Commodity]
# Signs reflect risk-off co-movement: when equities fall, yields fall (dy<0 with equity),
# spreads widen (dspread>0, i.e. negatively correlated with equity), commodities fall.
FACTOR_CORRELATIONS: list[list[float]] = [
    #  Equity  Rates  Credit  Comm
    [   1.00,  0.30,  -0.55,  0.45],   # Equity
    [   0.30,  1.00,  -0.35,  0.15],   # Rates (change in yield)
    [  -0.55, -0.35,   1.00, -0.30],   # Credit (change in spread)
    [   0.45,  0.15,  -0.30,  1.00],   # Commodity
]

# --- Asset universe & factor sensitivities ------------------------------------------
# exposure mapping (see methodology 6.1):
#   Equity    exposure = equity_beta
#   Rates     exposure = -eff_duration           (price ~ -D*dy + 0.5*C*dy^2)
#   Credit    exposure = -spread_duration
#   Commodity exposure = commodity_beta
ASSETS: list[dict] = [
    {"ticker": "SPY", "name": "S&P 500 ETF",                 "asset_class": "Equity",
     "equity_beta": 1.00, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.10, "convexity": 0.0,   "display_order": 1},
    {"ticker": "IEF", "name": "7-10y US Treasury ETF",       "asset_class": "Fixed Income - Rates",
     "equity_beta": -0.05, "eff_duration": 7.5, "spread_duration": 0.0, "commodity_beta": 0.00, "convexity": 75.0, "display_order": 2},
    {"ticker": "LQD", "name": "Investment-Grade Corp Bond ETF", "asset_class": "Fixed Income - Credit",
     "equity_beta": 0.20, "eff_duration": 8.4, "spread_duration": 8.4, "commodity_beta": 0.00, "convexity": 95.0, "display_order": 3},
    {"ticker": "GLD", "name": "Gold",                        "asset_class": "Commodity - Safe Haven",
     "equity_beta": -0.10, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.55, "convexity": 0.0,  "display_order": 4},
    {"ticker": "DBC", "name": "Broad Commodity Index",       "asset_class": "Commodity",
     "equity_beta": 0.35, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 1.00, "convexity": 0.0,  "display_order": 5},
]

# --- Calibrated stress scenarios ----------------------------------------------------
# Shocks in native factor units. Magnitudes calibrated to documented crisis moves
# (methodology 6.3).
SCENARIOS: list[dict] = [
    {
        "scenario_id": "GFC_2008", "name": "2008 Global Financial Crisis (acute)",
        "description": "Sep 2008-Mar 2009: equity collapse, flight to quality, IG spreads blow out, oil crash.",
        "is_historical": 1, "display_order": 1,
        "shocks": {"Equity": -0.45, "Rates": -0.0150, "Credit": 0.0400, "Commodity": -0.50},
    },
    {
        "scenario_id": "COVID_2020", "name": "2020 COVID Liquidity Freeze",
        "description": "Feb 19-Mar 23 2020: S&P -33.9%, yields to record lows, spreads +200bps, oil crash.",
        "is_historical": 1, "display_order": 2,
        "shocks": {"Equity": -0.34, "Rates": -0.0120, "Credit": 0.0200, "Commodity": -0.40},
    },
    {
        "scenario_id": "INFLATION_2026", "name": "Synthetic 2026 Inflation Spike",
        "description": "Forward-looking: yields rise sharply, bonds fall, credit widens modestly, real assets rally.",
        "is_historical": 0, "display_order": 3,
        "shocks": {"Equity": -0.15, "Rates": 0.0200, "Credit": 0.0150, "Commodity": 0.30},
    },
]

# Default illustrative portfolio (weights sum to 1.0).
DEFAULT_WEIGHTS: dict[str, float] = {"SPY": 0.40, "IEF": 0.20, "LQD": 0.20, "GLD": 0.10, "DBC": 0.10}

# History generation parameters.
N_WEEKS = 312          # ~6 years of weekly observations
RANDOM_SEED = 20260715  # fixed for reproducibility
IDIOSYNCRATIC_ANNUAL_VOL = 0.03  # asset-specific noise not explained by factors

FACTOR_ORDER = [f["name"] for f in FACTORS]
ASSET_ORDER = [a["ticker"] for a in ASSETS]
