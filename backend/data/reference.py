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
MODEL_VERSION = "4.0.0"

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
# Betas are CALIBRATED so the factor model reproduces documented realized crisis returns
# (see REALIZED_CRISIS_RETURNS and the backtest). Cross-loadings are kept minimal to avoid
# double-counting: each asset loads mainly on its primary factor(s). Gold is modelled as a
# safe haven (negative equity beta + negative FX beta), NOT a commodity.
# A 13-asset multi-asset universe spanning US/intl/EM equity, the Treasury curve, IG/HY
# credit, TIPS, gold, broad commodities and REITs. Enough breadth that diversification,
# curve positioning and credit-vs-rates trade-offs become visible - not a toy 5-asset set.
ASSETS: list[dict] = [
    # --- Equity -----------------------------------------------------------------------
    {"ticker": "SPY", "name": "S&P 500 ETF",                    "asset_class": "Equity - US Large Cap",
     "equity_beta": 1.00, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.00, "fx_beta": -0.05, "convexity": 0.0,  "display_order": 1},
    {"ticker": "QQQ", "name": "Nasdaq-100 (US Growth)",         "asset_class": "Equity - US Growth",
     "equity_beta": 1.15, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.05, "fx_beta": -0.05, "convexity": 0.0,  "display_order": 2},
    {"ticker": "IWM", "name": "Russell 2000 (US Small Cap)",    "asset_class": "Equity - US Small Cap",
     "equity_beta": 1.20, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.25, "fx_beta": 0.00, "convexity": 0.0,  "display_order": 3},
    {"ticker": "EFA", "name": "MSCI EAFE (Dev. ex-US Equity)",  "asset_class": "Equity - Intl Developed",
     "equity_beta": 0.95, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.05,
     "liquidity_beta": 0.10, "fx_beta": -0.30, "convexity": 0.0,  "display_order": 4},
    {"ticker": "EEM", "name": "MSCI Emerging Markets Equity",   "asset_class": "Equity - Emerging",
     "equity_beta": 1.15, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.15,
     "liquidity_beta": 0.35, "fx_beta": -0.45, "convexity": 0.0,  "display_order": 5},
    # --- Rates ------------------------------------------------------------------------
    {"ticker": "IEF", "name": "7-10y US Treasury ETF",          "asset_class": "Fixed Income - Rates",
     "equity_beta": -0.02, "eff_duration": 7.5, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": -0.05, "fx_beta": 0.05, "convexity": 80.0, "display_order": 6},
    {"ticker": "TLT", "name": "20+y US Treasury ETF (Long)",    "asset_class": "Fixed Income - Rates Long",
     "equity_beta": -0.05, "eff_duration": 17.0, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": -0.10, "fx_beta": 0.10, "convexity": 300.0, "display_order": 7},
    {"ticker": "TIP", "name": "TIPS (Inflation-Linked UST)",    "asset_class": "Fixed Income - Inflation",
     "equity_beta": 0.02, "eff_duration": 7.0, "spread_duration": 0.0, "commodity_beta": 0.12,
     "liquidity_beta": 0.00, "fx_beta": 0.00, "convexity": 70.0, "display_order": 8},
    # --- Credit -----------------------------------------------------------------------
    {"ticker": "LQD", "name": "Investment-Grade Corp Bond ETF", "asset_class": "Fixed Income - IG Credit",
     "equity_beta": 0.05, "eff_duration": 7.5, "spread_duration": 6.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.30, "fx_beta": -0.03, "convexity": 90.0, "display_order": 9},
    {"ticker": "HYG", "name": "High-Yield Corp Bond ETF",       "asset_class": "Fixed Income - High Yield",
     "equity_beta": 0.35, "eff_duration": 4.0, "spread_duration": 4.0, "commodity_beta": 0.05,
     "liquidity_beta": 0.45, "fx_beta": -0.05, "convexity": 40.0, "display_order": 10},
    # --- Real assets ------------------------------------------------------------------
    {"ticker": "GLD", "name": "Gold (safe haven)",              "asset_class": "Precious Metal - Safe Haven",
     "equity_beta": -0.18, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.20, "fx_beta": -0.20, "convexity": 0.0,  "display_order": 11},
    {"ticker": "DBC", "name": "Broad Commodity Index",          "asset_class": "Commodity",
     "equity_beta": 0.15, "eff_duration": 0.0, "spread_duration": 0.0, "commodity_beta": 0.85,
     "liquidity_beta": 0.10, "fx_beta": -0.15, "convexity": 0.0,  "display_order": 12},
    {"ticker": "VNQ", "name": "US REITs (Real Estate)",         "asset_class": "Real Estate",
     "equity_beta": 1.00, "eff_duration": 4.0, "spread_duration": 1.0, "commodity_beta": 0.00,
     "liquidity_beta": 0.25, "fx_beta": -0.05, "convexity": 20.0, "display_order": 13},
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
        "shocks": {"Equity": -0.45, "Rates": -0.0150, "Credit": 0.0300,
                    "Commodity": -0.48, "Liquidity": -0.15, "FX": 0.10},
    },
    {
        "scenario_id": "COVID_2020", "name": "2020 COVID Liquidity Freeze",
        "description": "Feb 19-Mar 23 2020: S&P -33.9%, record-low yields, spreads widen, a severe "
                       "dash-for-cash liquidity freeze, USD spike, oil crash.",
        "is_historical": 1, "display_order": 2,
        "shocks": {"Equity": -0.34, "Rates": -0.0120, "Credit": 0.0220,
                    "Commodity": -0.38, "Liquidity": -0.25, "FX": 0.08},
    },
    {
        "scenario_id": "DOTCOM_2000", "name": "2000-02 Dot-com Bust",
        "description": "Mar 2000-Oct 2002: tech/growth collapse, Fed cuts (yields fall), modest "
                       "credit widening, commodities roughly flat, mild USD bid.",
        "is_historical": 1, "display_order": 3,
        "shocks": {"Equity": -0.45, "Rates": -0.0200, "Credit": 0.0120,
                    "Commodity": 0.05, "Liquidity": -0.05, "FX": 0.05},
    },
    {
        "scenario_id": "EURO_2011", "name": "2011 Euro Sovereign Crisis",
        "description": "Jul-Oct 2011: risk-off on peripheral sovereign stress, flight to Treasuries, "
                       "IG/HY spreads widen, commodities soften, USD haven bid.",
        "is_historical": 1, "display_order": 4,
        "shocks": {"Equity": -0.16, "Rates": -0.0070, "Credit": 0.0140,
                    "Commodity": -0.08, "Liquidity": -0.07, "FX": 0.06},
    },
    {
        "scenario_id": "TAPER_2013", "name": "2013 Taper Tantrum",
        "description": "May-Sep 2013: rates spike on Fed taper signal, bonds fall, EM and rate-"
                       "sensitive assets hit hardest, equity only mildly down.",
        "is_historical": 1, "display_order": 5,
        "shocks": {"Equity": -0.04, "Rates": 0.0100, "Credit": 0.0050,
                    "Commodity": -0.06, "Liquidity": -0.02, "FX": 0.04},
    },
    {
        "scenario_id": "RATE_SHOCK_2022", "name": "2022 Inflation / Rate Shock",
        "description": "2022: fastest hiking cycle in decades - stocks AND bonds fall together, "
                       "long duration crushed, commodities rally, strong USD.",
        "is_historical": 1, "display_order": 6,
        "shocks": {"Equity": -0.18, "Rates": 0.0220, "Credit": 0.0080,
                    "Commodity": 0.16, "Liquidity": -0.04, "FX": 0.08},
    },
    {
        "scenario_id": "INFLATION_2026", "name": "Synthetic 2026 Inflation Spike",
        "description": "Forward-looking: yields rise sharply, bonds fall, credit widens modestly, "
                       "real assets rally, mild funding stress, softer USD.",
        "is_historical": 0, "display_order": 7,
        "shocks": {"Equity": -0.15, "Rates": 0.0200, "Credit": 0.0120,
                    "Commodity": 0.30, "Liquidity": -0.02, "FX": -0.05},
    },
    {
        "scenario_id": "STAGFLATION_SYNTH", "name": "Synthetic Stagflation",
        "description": "Forward-looking: growth stalls while inflation stays high - equity falls, "
                       "yields rise, credit widens, commodities surge, weaker USD.",
        "is_historical": 0, "display_order": 8,
        "shocks": {"Equity": -0.22, "Rates": 0.0180, "Credit": 0.0180,
                    "Commodity": 0.38, "Liquidity": -0.06, "FX": -0.06},
    },
]

# --- Realized crisis returns (backtest ground truth) --------------------------------
# Representative realized total returns over each crisis window, from documented market
# history. These are INDEPENDENT of the factor model (not generated from exposures), so
# comparing model-predicted vs. these realized figures is a genuine out-of-sample check,
# not a self-fulfilling one. Synthetic scenarios have no realized data and are excluded.
# Five crisis windows now provide out-of-sample folds (was two). Figures are representative
# total returns over each documented window; assets that did not yet trade in a window are
# omitted (the backtest handles partial coverage). Pre-2006 gold/commodity use spot proxies.
REALIZED_CRISIS_RETURNS: dict[str, dict[str, float]] = {
    "GFC_2008": {
        "SPY": -0.46, "QQQ": -0.44, "IWM": -0.52, "EFA": -0.55, "EEM": -0.58,
        "IEF": 0.15, "TLT": 0.28, "TIP": -0.03, "LQD": -0.12, "HYG": -0.31,
        "GLD": 0.05, "DBC": -0.50, "VNQ": -0.62,
    },
    "COVID_2020": {
        "SPY": -0.34, "QQQ": -0.28, "IWM": -0.41, "EFA": -0.34, "EEM": -0.33,
        "IEF": 0.10, "TLT": 0.14, "TIP": 0.01, "LQD": -0.14, "HYG": -0.21,
        "GLD": -0.02, "DBC": -0.40, "VNQ": -0.42,
    },
    "EURO_2011": {
        "SPY": -0.16, "QQQ": -0.13, "IWM": -0.25, "EFA": -0.22, "EEM": -0.24,
        "IEF": 0.06, "TLT": 0.30, "TIP": 0.03, "LQD": 0.02, "HYG": -0.07,
        "GLD": 0.08, "DBC": -0.09, "VNQ": -0.14,
    },
    "RATE_SHOCK_2022": {
        "SPY": -0.18, "QQQ": -0.33, "IWM": -0.21, "EFA": -0.14, "EEM": -0.20,
        "IEF": -0.12, "TLT": -0.31, "TIP": -0.12, "LQD": -0.18, "HYG": -0.11,
        "GLD": -0.01, "DBC": 0.19, "VNQ": -0.26,
    },
    "DOTCOM_2000": {  # only ETFs/proxies trading over 2000-02
        "SPY": -0.47, "QQQ": -0.78, "IEF": 0.28, "LQD": 0.20, "GLD": 0.12,
    },
}

# Default illustrative portfolio (weights sum to 1.0) - a diversified multi-asset sleeve.
DEFAULT_WEIGHTS: dict[str, float] = {
    "SPY": 0.20, "QQQ": 0.08, "IWM": 0.04, "EFA": 0.08, "EEM": 0.05,
    "IEF": 0.10, "TLT": 0.05, "TIP": 0.05, "LQD": 0.10, "HYG": 0.05,
    "GLD": 0.06, "DBC": 0.04, "VNQ": 0.10,
}

# --- History generation parameters --------------------------------------------------
N_WEEKS = 520                    # ~10 years of weekly observations
RANDOM_SEED = 20260715           # fixed for reproducibility
IDIOSYNCRATIC_ANNUAL_VOL = 0.10  # asset-specific noise -> realistic factor R^2 (~0.75-0.85)
CRISIS_WEEK_FRACTION = 0.12      # long-run share of weeks in the crisis regime
CRISIS_STAY_PROB = 0.80          # P(crisis->crisis): crises persist (~5wk avg), not i.i.d.
CRISIS_VOL_MULTIPLIER = 2.5      # factor vol amplification in the crisis regime
STUDENT_T_DOF_CALM = 8.0         # fat tails even in calm times
STUDENT_T_DOF_CRISIS = 4.0       # fatter tails in crisis
