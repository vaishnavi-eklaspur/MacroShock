-- MacroShock relational schema (SQLite; mirrors a Snowflake warehouse layout).
-- All monetary/return values are stored as decimals (e.g. -0.34 == -34%).

PRAGMA foreign_keys = ON;

-- Reference: the tradeable asset universe and its factor sensitivities.
CREATE TABLE IF NOT EXISTS assets (
    ticker          TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    asset_class     TEXT    NOT NULL,
    equity_beta     REAL    NOT NULL,   -- exposure to the Equity factor
    eff_duration    REAL    NOT NULL,   -- effective duration (years) -> rates exposure = -eff_duration
    spread_duration REAL    NOT NULL,   -- spread duration (years) -> credit exposure = -spread_duration
    commodity_beta  REAL    NOT NULL,   -- exposure to the Commodity factor
    convexity       REAL    NOT NULL DEFAULT 0.0,  -- bond convexity (for large-shock pricing)
    display_order   INTEGER NOT NULL DEFAULT 0
);

-- Reference: the macro risk factors.
CREATE TABLE IF NOT EXISTS factors (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    unit        TEXT NOT NULL,   -- 'return' | 'yield_change' | 'spread_change'
    annual_vol  REAL NOT NULL    -- annualized volatility used to build the factor covariance
);

-- Fact: weekly asset total returns.
CREATE TABLE IF NOT EXISTS asset_returns (
    ticker        TEXT NOT NULL,
    obs_date      TEXT NOT NULL,   -- ISO date (YYYY-MM-DD)
    weekly_return REAL NOT NULL,
    PRIMARY KEY (ticker, obs_date),
    FOREIGN KEY (ticker) REFERENCES assets(ticker)
);

-- Fact: weekly factor returns / changes (native units per `factors.unit`).
CREATE TABLE IF NOT EXISTS factor_returns (
    factor_name   TEXT NOT NULL,
    obs_date      TEXT NOT NULL,
    weekly_return REAL NOT NULL,
    PRIMARY KEY (factor_name, obs_date),
    FOREIGN KEY (factor_name) REFERENCES factors(name)
);

-- Reference: stress scenarios.
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id   TEXT PRIMARY KEY,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    is_historical INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0
);

-- Reference: the factor-shock vector that defines each scenario.
CREATE TABLE IF NOT EXISTS scenario_shocks (
    scenario_id TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    shock       REAL NOT NULL,   -- native units (return, yield_change, or spread_change)
    PRIMARY KEY (scenario_id, factor_name),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY (factor_name) REFERENCES factors(name)
);
