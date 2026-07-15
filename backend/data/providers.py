"""Pluggable return-data providers.

The analytics never assume where returns come from. This interface is the single swap point
between the shipped (calibrated, reproducible) synthetic data and real market data. To go
live you implement/enable one provider - no analytics change required.

Providers return a wide DataFrame of periodic returns: index = date (str/DatetimeIndex),
columns = tickers, values = periodic (weekly) total returns.
"""
from __future__ import annotations

import abc
from pathlib import Path

import pandas as pd


class ReturnsProvider(abc.ABC):
    """Abstract source of periodic asset returns."""

    @abc.abstractmethod
    def get_asset_returns(self) -> pd.DataFrame:
        """Wide DataFrame: index = date, columns = tickers, values = weekly returns."""
        raise NotImplementedError


class DatabaseProvider(ReturnsProvider):
    """Reads the seeded SQLite/warehouse table (the default, reproducible source)."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

    def get_asset_returns(self) -> pd.DataFrame:
        from . import database  # local import to avoid a cycle at module load
        return database.get_asset_returns(self.db_path)


class CsvReturnsProvider(ReturnsProvider):
    """Reads a CSV of weekly returns (first column = date, remaining columns = tickers).

    This is the simplest path to real data: export returns from any source to CSV and point
    the engine at this provider. Example CSV:

        date,SPY,IEF,LQD,GLD,DBC
        2020-01-03,0.012,-0.003,0.001,0.004,-0.010
        ...
    """

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def get_asset_returns(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path, index_col=0)
        return df.sort_index()


# Independent real-world proxies for the six macro factors (Yahoo tickers), in NATIVE units.
# Equity/Commodity/FX are clean total-return / index series. Rates is the weekly change in the
# 10y yield. Credit is a documented HY-excess proxy for spread change. Liquidity has no clean
# free proxy — a licensed funding-stress series (Aladdin/Bloomberg) is required, so it is left
# at zero here and flagged, rather than faked. Using these makes the factors INDEPENDENT of the
# assets (not a projection of them), so estimated betas and R² are honest.
FACTOR_PROXY_TICKERS = {
    "Equity": "^GSPC",        # S&P 500 total move
    "Commodity": "^SPGSCI",   # S&P GSCI commodity index
    "FX": "DX-Y.NYB",         # US Dollar Index (DXY)
    "Rates": "^TNX",          # 10y Treasury yield (percent) -> weekly change / 100
    "Credit_HY": "HYG",       # high-yield ETF, for the credit-spread proxy
    "Credit_RF": "IEF",       # duration-ish Treasury leg for the credit proxy
}


def download_factor_proxies(start: str = "2010-01-01", end: str | None = None) -> "pd.DataFrame":
    """Weekly factor returns in native units from INDEPENDENT real proxies (requires yfinance).

    This is the non-circular real-data path: factors come from their own market series, not
    from the portfolio's assets. Returns columns in FACTOR_ORDER; Liquidity is 0.0 (no clean
    free proxy — documented, not fabricated).
    """
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance required for --source yahoo factor proxies.") from exc

    from .reference import FACTOR_ORDER

    tk = list({t for t in FACTOR_PROXY_TICKERS.values()})
    px = yf.download(tk, start=start, end=end, auto_adjust=True, progress=False)["Close"]
    wk = px.resample("W-FRI").last()
    ret = wk.pct_change()
    dyield = wk[FACTOR_PROXY_TICKERS["Rates"]].diff() / 100.0     # percent -> decimal Δyield

    out = pd.DataFrame(index=wk.index)
    out["Equity"] = ret[FACTOR_PROXY_TICKERS["Equity"]]
    out["Rates"] = dyield
    # Credit spread change proxy: HY underperformance vs the Treasury leg, per unit spread dur.
    out["Credit"] = -(ret[FACTOR_PROXY_TICKERS["Credit_HY"]]
                      - ret[FACTOR_PROXY_TICKERS["Credit_RF"]]) / 4.0
    out["Commodity"] = ret[FACTOR_PROXY_TICKERS["Commodity"]]
    out["Liquidity"] = 0.0   # no clean free proxy; needs a licensed funding-stress series
    out["FX"] = ret[FACTOR_PROXY_TICKERS["FX"]]
    return out[FACTOR_ORDER].dropna(how="any")


class YFinanceReturnsProvider(ReturnsProvider):
    """Live provider (requires network + `yfinance`). Import-guarded so it never breaks the
    default build. Downloads adjusted closes and computes weekly total returns.

    Enable by installing yfinance and constructing:
        YFinanceReturnsProvider(["SPY","IEF","LQD","GLD","DBC"], start="2010-01-01")
    """

    def __init__(self, tickers: list[str], start: str = "2010-01-01",
                 end: str | None = None):
        self.tickers = tickers
        self.start = start
        self.end = end

    def get_asset_returns(self) -> pd.DataFrame:
        try:
            import yfinance as yf  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "yfinance is not installed. `pip install yfinance` to use live data, or use "
                "CsvReturnsProvider / DatabaseProvider instead."
            ) from exc
        prices = yf.download(self.tickers, start=self.start, end=self.end,
                             auto_adjust=True, progress=False)["Close"]
        weekly = prices.resample("W-FRI").last()
        return weekly.pct_change().dropna(how="all")
