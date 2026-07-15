"""Real-data ingestion: factor returns derived from asset returns by projection.

The exposure matrix B (13x6) is full column rank, so f_t = pinv(B) a_t is an exact left
inverse: noiseless asset returns generated as A = F Bᵀ must recover F exactly. With noise,
recovery is approximate. This guards the real-data seed path (CSV / Yahoo).
"""
import numpy as np
import pandas as pd

from data import seed
from data.reference import ASSETS, FACTOR_ORDER


def test_derive_factor_returns_recovers_known_factors():
    rng = np.random.default_rng(0)
    B = seed._exposure_matrix()                       # n_assets x n_factors
    tickers = [a["ticker"] for a in ASSETS]

    F = rng.standard_normal((200, len(FACTOR_ORDER))) * 0.01     # true factor returns
    A = F @ B.T                                                   # noiseless asset returns
    asset_df = pd.DataFrame(A, columns=tickers)

    derived = seed._derive_factor_returns(asset_df)
    assert list(derived.columns) == FACTOR_ORDER
    assert np.allclose(derived.to_numpy(), F, atol=1e-8)          # exact recovery, full rank


def test_build_returns_falls_back_to_synthetic_on_bad_source():
    # A bad CSV path must not crash the seed - it degrades to reproducible synthetic data.
    adf, fdf, prov = seed.build_returns("csv", csv_path="/nonexistent.csv",
                                        start="2010-01-01", end=None)
    assert "synthetic" in prov["source"]
    assert adf.shape[1] == len(ASSETS)
    assert list(fdf.columns) == FACTOR_ORDER
