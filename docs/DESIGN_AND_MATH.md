# MacroShock — Design Decisions & Math (interview defense)

A one-page map of *what* each piece does, *why* it's built that way, and *how to defend it*.
Every claim here is backed by code in `backend/analytics/` and tested in `backend/tests/`.

---

## The one-sentence pitch
A modular, multi-asset **stress-testing and portfolio-construction** engine: given a portfolio
and a macro shock, it decomposes *why* it breaks (factors + holdings, regime-aware), quantifies
the *tail*, measures it *against a benchmark* (tracking error, active risk, factor tilts), and
proposes a *constrained* mitigation trade — behind a typed API, two UIs, and Docker/Azure deploy.

## The math, and why each choice

| Component | What | Why this choice | Defend it with |
|---|---|---|---|
| **Covariance** | Ledoit–Wolf **constant-correlation** shrinkage | Sample covariance is noisy when T isn't ≫ N; constant-correlation target keeps assets correlated (identity target wrongly shrinks correlations to 0) | `portfolio.ledoit_wolf_constant_correlation`; L&W (2003) |
| **Regime detection** | χ²-threshold on **Mahalanobis** distance of weekly returns | A *principled* test, not a top-x% quantile — on calm data it fires ~(1−p), so a regime is detected only if one exists | `regime.crisis_mask`; sq-Mahalanobis ~ χ²(n) under normality |
| **Regime cov** | Separate **crisis-conditional** covariance | Correlations tighten in stress; one full-sample cov understates crisis risk and hides the risk-share shift | `regime.conditional_covariance` |
| **Factor betas** | **Estimated by OLS** on independent factor history | Makes it a *factor model*, not a rotation of the assets. Honest R² ≈ 0.64 (not ~1.0). Structural betas kept for interpretable scenario pricing | `factors.estimate_exposures`, `test_exposures.py` |
| **Risk attribution** | Euler **MCTR/CCTR/PCTR** + block-bootstrap CIs | Sums to σ exactly (homogeneity degree 1); bootstrap CIs stop over-reading a noisy point estimate | `risk.py` |
| **Tail risk** | Gaussian vs **Historical / Cornish–Fisher / Student-t** VaR & CVaR, with Jarque–Bera + CF validity check | A stress tool that assumes normality is a contradiction; CF is only shown where its quantile map is monotone | `portfolio.py` |
| **Reverse stress** | Min-**Mahalanobis** shock hitting a target loss, *constrained* (bounds/signs) + top-k single-factor paths | The unconstrained closed form gives nonsense (e.g. tightening spreads); constraints + a plausibility (σ) score make it usable | `reverse.py` |
| **Benchmark-relative** | **Tracking error, active-risk contribution, factor tilts** vs a strategic benchmark | This is the actual IPS job: model portfolios are managed *relative to* a benchmark | `benchmark.py`, `test_benchmark.py` |
| **Rebalance** | **Constrained SLSQP** min-variance s.t. long-only, turnover cap, no-worse drawdown | A pose-and-solve a risk desk expects, not a greedy heuristic | `rebalance.optimize_rebalance` |
| **Backtest** | **Leave-one-crisis-out**, betas fit on weekly data, vs naive benchmarks with a skill ratio | Leakage-free: exposures never see the crisis they predict | `backtest.py` |

## The honesty points (say these before they ask)
- **The factor model is not circular.** Factors are independent series; betas are OLS-fit; R² is
  ~0.64, deliberately below 1. If factors were derived from the assets, R² would be ~1 and the
  model would be a tautology — see `test_exposures.py::test_projection_would_be_tautological`.
- **The backtest is genuinely out-of-sample and shows *negative* skill** across 5 heterogeneous
  crises. That's the honest result: predicting the *next crisis's shape* is forecasting, which
  the tool disclaims. Its validated claim is **conditional pricing** (given a shock, decompose the
  impact) — confirmed by the in-sample check (MAE ~5%) and the attribution outputs.
- **Data ships synthetic** (reproducible, two-regime, fat-tailed) and is **one flag from real**
  (`--source yahoo`), with the source reported at `/api/meta`.
- **"Snowflake" is a SQLite mock** with a real, import-guarded Snowflake adapter behind it
  (`snowflake_real.py`); I know the dialect differs (PRAGMA, `MERGE` vs upsert) and say so.

## Architecture & the "how"
Layered and decoupled: `data` (repository + warehouse dispatcher) → `analytics` (pure, tested
functions) → `engine` (orchestration) → `api` (Flask, pydantic-validated, Redis-cached, rate-
limited, `/metrics`) → UI (**Streamlit** for the analyst dashboard, **React+TypeScript** for the
typed client). Model-versioned cache keys guarantee a model change can never serve a stale number.
Docker Compose for local; Azure Container Apps (min-replicas=1) for always-on deploy.

## Limitations, and what I'd do with a real data platform
This is a self-contained demo. With BlackRock's platforms I would:
- **Aladdin** — replace hand-set exposures and the ETF universe with security-level analytics
  (real bond cash flows, option greeks, issuer-level credit), and use Aladdin's risk factors and
  scenario library instead of a 6-factor proxy set.
- **Bloomberg / FactSet / Morningstar** — real factor histories (yields, OAS credit spreads, FX)
  and holdings data, so betas are estimated on licensed data, not proxies; a proper credit-spread
  and funding-liquidity factor (the two I proxy weakest today).
- **MPI** — returns-based and holdings-based style analysis to validate the factor exposures.
- **Production** — Snowflake for the warehouse (real DDL/`MERGE`), Postgres for app state instead
  of SQLite, shared Redis rate limiting, and CI/CD to Azure with observability wired to `/metrics`.

The point of naming these: I understand the ceiling of a self-contained demo — and *the how is as
important as the what.*
