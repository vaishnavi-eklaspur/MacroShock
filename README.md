# MacroShock

**A portfolio consulting co-pilot** — it tells a portfolio manager not just *what* breaks
under a macro shock, but *why* it breaks, *which holding* is to blame, and *the single trade*
that reduces the pain. Built around factor-based stress testing, risk attribution, and reverse
stress testing — the same vocabulary institutional risk platforms (Aladdin-style) use.

> This is an educational/demonstration project. It is **not** investment advice and **not** a
> regulatory-grade risk system. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

---

## What makes it different

Most portfolio projects stop at "your portfolio dropped 18%." MacroShock adds three
institutional-grade capabilities:

1. **Factor attribution & risk decomposition (MCTR/CCTR).** Shows that a 40% *capital* weight
   can be 70% of the *risk*, and pins the loss on specific holdings and macro factors.
2. **Reverse stress testing.** Solves for the *most plausible* combination of factor shocks
   that would produce a target loss — a closed-form minimum-Mahalanobis solve.
3. **Auto-generated investment commentary.** Turns the numbers into a portfolio-manager
   narrative, deterministically (auditable, no LLM).

Every formula is documented and independently verified — see
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and `scripts/verify_math.py`.

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
