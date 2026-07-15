# MacroShock

**A portfolio consulting co-pilot** — it tells a portfolio manager not just *what* breaks
under a macro shock, but *why* it breaks, *which holding* is to blame, and *the single trade*
that reduces the pain. Built around factor-based stress testing, risk attribution, and reverse
stress testing — the same vocabulary institutional risk platforms use.

> This is an educational/demonstration project. It is **not** investment advice and **not** a
> regulatory-grade risk system. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

---

## What makes it different

Most portfolio projects stop at "your portfolio dropped 18%." MacroShock adds
institutional-grade capabilities and — importantly — is built to survive scrutiny:

1. **Regime-conditional risk attribution (MCTR/CCTR).** Shows that a 40% *capital* weight can
   be 70% of the *risk*, and that a holding's risk share **shifts** from the calm regime to
   the crisis regime as correlations tighten. Pins the loss on specific holdings and factors.
2. **Reverse stress testing — constrained + top-k.** Solves for the *most plausible* (bounded)
   combination of factor shocks that produces a target loss, and ranks the top single-factor
   paths by plausibility.
3. **Fat-tailed risk.** Gaussian VaR shown next to Historical, Cornish–Fisher (skew/kurtosis)
   and Student-t VaR/CVaR — because a stress tool that assumes normality is a contradiction.
4. **Backtest vs. reality.** The factor-shock engine's predictions are compared against
   **independent, documented** 2008/2020 crisis returns (MAE/RMSE), not against itself.
5. **Auto-generated investment commentary.** Deterministic, auditable PM-style narrative.

Under the hood: a **6-factor** model (Equity, Rates, Credit, Commodity, **Liquidity, FX**),
**regime-switching fat-tailed** data generation, **Ledoit–Wolf shrinkage** covariance, OLS
betas with **t-stats and R²**, pydantic-validated API, and a **model-versioned** cache.

Every formula is documented and independently verified — see
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) (including a **Limitations** section) and
`scripts/verify_math.py`.

---

## Architecture

```
Streamlit dashboard  ──REST──▶  Flask API  ──▶  Redis cache (expensive analytics)
                                    │
                                    ▼
                           Analytics core (numpy)  ──▶  Data layer
                     returns · vol · VaR/CVaR · OLS      SQLite via a
                     betas · MCTR · reverse-stress       mock Snowflake connector
```

| Layer | Tech | Role |
|---|---|---|
| Presentation | **Streamlit** + Plotly | sliders, scenario select, before/after, MCTR chart, commentary |
| API | **Flask** | `/load`, `/stress-test`, `/reverse-stress-test`, `/rebalance`, `/risk-contribution`, `/commentary` |
| Cache | **Redis** | caches covariance / regression / reverse-stress results; graceful fallback |
| Analytics | **Python + numpy/scipy** | pure, tested functions (see methodology) |
| Data | **SQL / SQLite** + mock **Snowflake** connector | returns, factor data, scenarios |
| Deploy | **Docker** + docker-compose | one-command spin-up |

---

## Run it

```bash
docker-compose up --build
```

Then open the dashboard at <http://localhost:8501>. The API is at <http://localhost:5000>.

### Run locally without Docker

```bash
cd backend
pip install -r requirements.txt
python -m data.seed            # build the SQLite database
flask --app app run            # API on :5000  (Redis optional; degrades gracefully)

cd ../frontend
pip install -r requirements.txt
streamlit run streamlit_app.py # dashboard on :8501
```

### Verify the math (no heavy dependencies)

```bash
python scripts/verify_math.py
```

This independently re-derives portfolio volatility, VaR, OLS betas, the MCTR Euler identity,
and the reverse-stress solver using only the Python standard library, and checks them against
hand-computed values.

### Tests

```bash
cd backend && pytest
```

---

## Asset universe

| Ticker | Name | Class |
|---|---|---|
| SPY | S&P 500 ETF | Equity |
| IEF | 7–10y US Treasury ETF | Fixed Income (rates) |
| LQD | Investment-grade corporate bond ETF | Fixed Income (credit) |
| GLD | Gold | Commodity / safe haven |
| DBC | Broad commodity index | Commodity |

## Scenarios

- **2008 GFC (acute)** · **2020 Liquidity Freeze** · **Synthetic 2026 Inflation Spike**

Magnitudes are calibrated to documented crisis moves; see the methodology doc.
