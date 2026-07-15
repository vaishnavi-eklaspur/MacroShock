# MacroShock

**A multi-asset stress-testing and portfolio-construction engine.** Given a portfolio and a
macro shock, it decomposes *why* the portfolio breaks (which factors, which holdings,
regime-aware), quantifies the *tail*, measures the book *against a benchmark* (tracking error,
active risk, factor tilts), and proposes a *constrained* mitigation trade — the vocabulary of
an institutional risk desk, in a small, tested, deployable stack.

[![CI](https://github.com/vaishnavi-eklaspur/MacroShock/actions/workflows/ci.yml/badge.svg)](https://github.com/vaishnavi-eklaspur/MacroShock/actions/workflows/ci.yml)

**Live demo:** dashboard → `https://YOUR-APP.streamlit.app` · API → <https://macroshock-api.onrender.com/health>

> Educational demonstration on real market data — **not** investment advice, **not** a
> regulatory-grade system. Its limits are stated explicitly below and in
> [`docs/DESIGN_AND_MATH.md`](docs/DESIGN_AND_MATH.md).

---

## It fits the model, not the noise

The quickest way to see the engine is real: seeded on live market data (2015–present), the
factor betas are **estimated by OLS** and recover known economic structure — not curve-fit.

| Holding | Estimated exposure | Ground truth |
|---|---|---|
| IEF (7–10y Treasury) | Rates **−7.31** | ≈ its ~7.5y effective duration |
| TLT (20y+ Treasury) | Rates **−15.75** | ≈ its ~17y duration |
| SPY | Equity **1.00** | it *is* the market |
| GLD / EEM / EFA | FX **−0.84 / −0.66 / −0.70** | all fall against a strong USD |

Mean R² ≈ **0.79** on real weekly data — deliberately *not* ~1.0. The factors are independent
series (real proxies or a projection-free CSV), so a genuine share of return stays
idiosyncratic. If the factors were derived from the assets, R² would be ~1.0 and the "factor
model" would be circular — a trap the code explicitly tests against.

## What makes it more than a stock tracker

- **Regime-conditional risk attribution.** MCTR/CCTR decomposition (Euler identity, with
  block-bootstrap confidence intervals) shows a 40% *capital* weight can be 70% of the *risk* —
  and that the risk share **shifts** from the calm to the crisis regime as correlations tighten.
- **Benchmark-relative analytics** — tracking error (calm *and* crisis), active-risk
  contribution, factor tilts and active share vs. a strategic benchmark. This is how multi-asset
  model portfolios are actually managed: relative to a benchmark, not in absolute terms.
- **Fat-tailed risk done honestly.** Gaussian VaR sits next to Historical, Cornish–Fisher and
  Student-t VaR/CVaR, with a Jarque–Bera normality test and a validity check on the CF
  expansion — because a stress tool that assumes normality is a contradiction.
- **Reverse stress testing.** Solves for the *most plausible* (bounded, sign-constrained) joint
  factor shock that produces a target loss, scored by Mahalanobis distance, with ranked
  single-factor alternatives.
- **A backtest that can fail.** Leave-one-crisis-out across five documented crises (dot-com,
  GFC, Euro 2011, COVID, 2022), with betas fit only on the weekly history so they never see the
  crisis they predict. It reports skill vs. naive benchmarks **honestly** — including where the
  model has none, because forecasting the next crisis's shape is not what the tool claims to do.
- **Statistical rigor on display, not hidden** — constant-correlation Ledoit–Wolf shrinkage,
  chi-square regime detection (not a top-x% quantile), VIF and condition-number
  multicollinearity diagnostics, a model-versioned cache so a recalibration can never serve a
  stale number.

## Architecture

```
React + TS client ─┐
                   ├─REST→  Flask API  ──→  Redis cache (graceful fallback)
Streamlit dashboard┘        (pydantic,        │
                            rate-limited,     ▼
                            /metrics)   Analytics core (numpy/scipy) ──→ Data layer
                                        cov · VaR/CVaR · OLS betas       SQLite (or real
                                        MCTR · reverse-stress · TE       Snowflake adapter)
```

| Layer | Tech | Notes |
|---|---|---|
| UI | **Streamlit** dashboard + **React/TypeScript** client (`frontend-react/`) | two independent front-ends over one typed API |
| API | **Flask** + pydantic | validated, Redis-cached, API-key + rate-limited, `/metrics` |
| Analytics | **Python / numpy / scipy** | pure, tested functions ([`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)) |
| Data | **SQL** (SQLite mock **or** real **Snowflake** adapter) | warehouse dispatcher swaps mock↔Snowflake by env var |
| Deploy | **Docker Compose**, **Render** (`render.yaml`), **Azure** (`deploy/azure/`) | one command locally; two clicks to the cloud |

## Run it

```bash
docker compose up --build
```
Dashboard → <http://localhost:8501> · API → <http://localhost:5050> · React → <http://localhost:5173>

<details>
<summary>Without Docker, real data, tests</summary>

```bash
# Backend (Python 3.11)
cd backend && pip install -r requirements.txt
python -m data.seed && flask --app app run -p 5050

# Real market data (falls back to synthetic if Yahoo is unreachable):
python -m data.seed --source yahoo --start 2015-01-01

# Streamlit dashboard  /  React client
cd frontend && pip install -r requirements.txt && streamlit run streamlit_app.py
cd frontend-react && npm install && npm run dev

# Tests + a dependency-free re-derivation of every formula
cd backend && pytest -q && python ../scripts/verify_math.py
```
</details>

## Universe & scenarios

**13 assets** across US/intl/EM equity, the Treasury curve (IEF/TLT/TIP), IG & HY credit, gold,
commodities and REITs. **8 scenarios** (2000 dot-com, 2008 GFC, 2011 Euro, 2013 taper, 2020
COVID, 2022 rate shock, plus synthetic inflation & stagflation) — or build any shock
interactively in the *Scenario builder* tab.

## Honest limitations

- **ETF-level, single-period linear pricing** — not security-level, no instrument cash flows or
  option greeks. This is a factor demo, not Aladdin.
- **On real data, Credit and Liquidity are proxies** (HY-excess and VIX); a licensed feed
  (Bloomberg OAS, a funding-stress series) is the production fix.
- **Five crises** is enough to be indicative out-of-sample, not statistically conclusive.
- The deployed dataset is a **committed real-data snapshot**, because Yahoo blocks datacenter
  IPs; the live `--source yahoo` path exists but can't run from a cloud host.

Naming these is the point: the engine is built to survive scrutiny, and *the how is as
important as the what*. Full derivations, calibration sources and the design rationale are in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and [`docs/DESIGN_AND_MATH.md`](docs/DESIGN_AND_MATH.md).
