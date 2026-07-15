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
4. **Backtest vs. reality.** Leave-one-crisis-out out-of-sample test across **five**
   independent, documented crises (dot-com, GFC, Euro 2011, COVID, 2022) with a **skill score**
   against naive benchmarks — not scored against itself.
5. **Auto-generated investment commentary.** Deterministic, auditable PM-style narrative.
6. **Real or synthetic data, one flag.** `python -m data.seed --source yahoo` pulls live prices
   (factor histories derived by projection onto the exposure matrix); offline it degrades
   gracefully to reproducible synthetic data, and `/api/meta` always reports which is live.
7. **Interactive dashboard.** Build custom shock scenarios, compare two portfolios side by side,
   save/load named portfolios (persisted server-side), and export a CSV/HTML consulting report.

Under the hood: a **6-factor** model (Equity, Rates, Credit, Commodity, **Liquidity, FX**),
**persistent (Markov) regime-switching** fat-tailed data, **constant-correlation Ledoit–Wolf**
shrinkage, **chi-square regime detection** (no top-x% selection bias), **regime-conditional**
risk attribution with **bootstrap confidence intervals**, **out-of-sample** cross-crisis
backtesting with a **skill score**, a **Jarque–Bera** normality test with an **MLE-fitted
Student-t** dof, **VIF / condition-number** multicollinearity diagnostics, a **constrained
(SLSQP) optimizer** rebalance, a pluggable **real-data provider** interface, pydantic-validated
API, and a **model-versioned** cache.

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
python -m data.seed            # build the SQLite database (synthetic, reproducible)
flask --app app run            # API on :5000  (Redis optional; degrades gracefully)

cd ../frontend
pip install -r requirements.txt
streamlit run streamlit_app.py # dashboard on :8501
```

### Use real market data

```bash
pip install yfinance
python -m data.seed --source yahoo --start 2012-01-01   # live prices; falls back offline
# or bring your own weekly-returns CSV (date,SPY,IEF,…):
python -m data.seed --source csv --csv my_returns.csv
```

### Lock it down (optional)

Set `MACROSHOCK_API_KEY` to require an `X-API-Key` header on write endpoints; the dashboard
reads the same variable. `MACROSHOCK_RATE_PER_MIN` caps write requests per IP per minute.

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

## Asset universe (13)

| Class | Tickers |
|---|---|
| Equity | SPY (US large), QQQ (growth), IWM (small), EFA (intl dev), EEM (EM) |
| Rates | IEF (7–10y UST), TLT (20y+ UST), TIP (TIPS) |
| Credit | LQD (IG), HYG (high yield) |
| Real assets | GLD (gold), DBC (commodities), VNQ (REITs) |

Each asset carries documented factor sensitivities (equity/commodity/liquidity/FX betas,
effective & spread durations, convexity) — see [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Scenarios (8)

Historical: **2000 dot-com**, **2008 GFC**, **2011 Euro crisis**, **2013 taper**,
**2020 COVID freeze**, **2022 rate shock**. Synthetic: **2026 inflation spike**,
**stagflation**. Magnitudes are calibrated to documented crisis moves.

You can also **build any scenario interactively** in the dashboard's *Scenario builder* tab.
