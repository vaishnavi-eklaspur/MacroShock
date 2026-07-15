# Product Requirements Document (PRD)

## MacroShock — Multi-Asset Portfolio Stress-Testing & Factor Attribution Engine

| Field | Value |
|---|---|
| **Document Owner** | Vaishnavi Eklaspur |
| **Status** | Draft v1.0 |
| **Last Updated** | 15 July 2026 |
| **Target Audience** | BlackRock — Investment & Portfolio Solutions (IPS) Technology |
| **Project Type** | 1-Day Portfolio / Interview Showcase Project |
| **Est. Build Time** | ~9 focused engineering hours |

---

## 1. Executive Summary

**MacroShock** is a modular, containerized web application that lets a user construct a multi-asset portfolio (equities, fixed income, commodities) and simulate its behaviour under severe historical and synthetic macroeconomic shocks — for example the 2008 Global Financial Crisis, the 2020 COVID liquidity freeze, or a forward-looking 2026 inflation spike.

Crucially, MacroShock does not merely report a decline in portfolio value. It performs **factor attribution** to explain *why* the portfolio moved (interest-rate risk, growth-factor exposure, currency volatility, credit spread widening) and recommends a **modular rebalancing strategy** to mitigate the specific vulnerability the shock exposed.

The project deliberately mirrors the analytical and architectural DNA of BlackRock's Aladdin platform — risk management, multi-asset construction, and stress testing — while demonstrating enterprise-grade software practices: decoupled layers, caching of expensive computations, RESTful API design, unit testing, and single-command container deployment.

---

## 2. Problem Statement

Portfolio managers and investment strategists need to understand not just *how much* a portfolio might lose in a crisis, but *what underlying risk factors* drive that loss. Generic portfolio trackers show a single bottom-line return and stop there. They provide no attribution, no scenario intelligence, and no actionable mitigation.

**The gap:** There is no lightweight, fast, explainable tool that connects a portfolio's allocation to its factor exposures and translates a macro shock into a concrete, prioritized rebalancing recommendation.

**The opportunity:** Build a compact engine that treats risk *attribution* as a first-class output, delivered through a responsive UI backed by a cache-accelerated analytics pipeline.

---

## 3. Goals & Non-Goals

### 3.1 Goals
- Allow a user to define a multi-asset portfolio via weights across a curated asset universe.
- Simulate portfolio performance under selectable historical and synthetic macro shock scenarios.
- Decompose portfolio risk into interpretable factor loadings (e.g., Growth, Inflation, Rates, Credit).
- Recommend a rebalancing strategy that reduces exposure to the dominant risk driver of the selected shock.
- Demonstrate production-grade architecture: modular Python core, Flask API, Redis caching, Dockerized deployment.
- Deliver an interactive dashboard showing the portfolio's "before vs. after" state and shifting factor exposures.

### 3.2 Non-Goals
- **Not** a live trading or order-execution system.
- **Not** a real-time market data feed integration (uses curated/mock historical datasets).
- **Not** a regulatory-grade risk engine — this is an illustrative showcase, not a certified VaR model.
- **Not** a user authentication / multi-tenant SaaS product (single-user local scope for v1).
- **Not** intended to give investment advice; outputs are educational demonstrations.

---

## 4. Target Users & Personas

| Persona | Description | Primary Need |
|---|---|---|
| **Priya — Portfolio Strategist** | Constructs multi-asset portfolios and consults with clients. | Understand *which factor* drives losses under a given scenario, and how to hedge it. |
| **Arjun — Quant Developer (IPS)** | Builds analytics tooling. | A clean, modular, testable codebase that separates math from API from UI. |
| **Reviewer — Hiring Manager (BlackRock IPS)** | Evaluating the candidate. | Evidence of business empathy, software craftsmanship, and Aladdin-aligned thinking. |

---

## 5. User Stories

- **US-1:** As a strategist, I want to enter portfolio weights across several asset classes so I can model my current allocation.
- **US-2:** As a strategist, I want to select a historical or synthetic shock scenario so I can see how my portfolio would react.
- **US-3:** As a strategist, I want to see a factor attribution breakdown so I understand *why* my portfolio moved, not just by how much.
- **US-4:** As a strategist, I want a suggested rebalance that reduces my largest risk exposure so I can act on the insight.
- **US-5:** As a developer, I want the analytics logic isolated in pure, tested Python functions so it can be reused and validated independently.
- **US-6:** As a developer, I want repeated stress tests on unchanged inputs to return instantly so the app feels responsive.
- **US-7:** As a reviewer, I want to run the entire stack with a single command so I can evaluate it without setup friction.

---

## 6. Functional Requirements

### 6.1 Portfolio Definition
- **FR-1.1:** System shall provide a curated asset universe of ~5 assets spanning equities, fixed income, and commodities (e.g., S&P 500 ETF, 10-Year Treasury ETF, Gold, Investment-Grade Corporate Bond ETF, Broad Commodity Index).
- **FR-1.2:** User shall assign percentage weights to each asset; weights shall sum to 100% (system validates and normalizes).
- **FR-1.3:** System shall persist and retrieve portfolio definitions via the data layer.

### 6.2 Scenario Engine
- **FR-2.1:** System shall offer a selectable list of shock scenarios: **2008 GFC**, **2020 Liquidity Freeze**, and a **Synthetic 2026 Inflation Spike**.
- **FR-2.2:** Each scenario shall map to a defined set of asset-class return shocks and factor index movements over the crisis window.
- **FR-2.3:** System shall compute the portfolio's simulated return path and terminal drawdown under the selected scenario.

### 6.3 Analytics & Attribution
- **FR-3.1:** System shall compute portfolio **volatility** and **Value at Risk (VaR)** at a configurable confidence level (default 95%).
- **FR-3.2:** System shall compute **factor loadings (Beta)** of the portfolio against macro factors (Growth, Inflation, Rates, Credit) via linear regression on historical returns.
- **FR-3.3:** System shall produce a **factor attribution** view showing each factor's contribution to the total shock-driven loss.
- **FR-3.4:** System shall generate a **rebalancing recommendation** that reduces the portfolio's exposure to the dominant contributing factor for the selected scenario.

### 6.4 API Layer
- **FR-4.1:** Expose `POST /api/portfolio/load` — accept and validate a portfolio definition.
- **FR-4.2:** Expose `POST /api/portfolio/stress-test` — run a scenario and return returns, VaR, and factor attribution as JSON.
- **FR-4.3:** Expose `POST /api/portfolio/rebalance` — return a recommended set of adjusted weights and the projected risk improvement.
- **FR-4.4:** All endpoints shall return structured JSON with clear error codes and validation messages.

### 6.5 Caching
- **FR-5.1:** System shall generate a deterministic cache key from `(asset weights + scenario id + confidence level)`.
- **FR-5.2:** On a stress-test request, if the key exists in Redis, return the cached result; otherwise compute, store, and return.
- **FR-5.3:** Cached covariance matrices and factor-loading results shall have a configurable TTL.

### 6.6 Presentation Layer
- **FR-6.1:** UI shall provide sliders/inputs for adjusting asset weights and a dropdown to select the shock scenario.
- **FR-6.2:** UI shall display a **before-vs-after** portfolio value comparison under the shock.
- **FR-6.3:** UI shall render an **interactive factor-exposure matrix / bar chart** visualizing shifting exposures during the shock.
- **FR-6.4:** UI shall surface the rebalancing recommendation and its projected risk reduction.

---

## 7. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Performance** | A cached stress-test response shall return in < 200 ms; a cold computation shall complete in < 2 s for the reference universe. |
| **Modularity** | Analytics math shall live in pure, side-effect-free Python functions with no Flask/Redis dependencies, enabling independent reuse and testing. |
| **Testability** | Core analytics functions (returns, volatility, VaR, factor regression) shall be covered by unit tests. |
| **Portability** | Entire stack shall launch via `docker-compose up` with no manual setup beyond Docker. |
| **Reliability** | API shall gracefully degrade if Redis is unavailable (compute directly, log a warning). |
| **Maintainability** | Clear separation of concerns: `data / analytics / api / ui` modules. |
| **Observability** | Structured logging on API requests, cache hits/misses, and computation timings. |

---

## 8. System Architecture

A highly modular, decoupled, container-orchestrated design.

```
                ┌─────────────────────────────────────────────┐
                │              Presentation Layer               │
                │        Streamlit / React Dashboard            │
                │  (weight sliders, scenario select, charts)    │
                └───────────────────────┬───────────────────────┘
                                        │  REST / JSON
                ┌───────────────────────▼───────────────────────┐
                │                 API Layer (Flask)              │
                │  /load   /stress-test   /rebalance             │
                └──────────┬───────────────────────┬────────────┘
                           │                        │
              cache lookup │                        │ compute
                           ▼                        ▼
                ┌──────────────────┐     ┌────────────────────────┐
                │  Caching Layer   │     │   Analytics Pipeline    │
                │     (Redis)      │     │       (Pure Python)     │
                │  cov matrices,   │     │  returns, VaR, vol,     │
                │  factor loadings │     │  factor regression,     │
                └──────────────────┘     │  rebalancing logic      │
                                         └───────────┬─────────────┘
                                                     │
                                        ┌────────────▼─────────────┐
                                        │        Data Layer         │
                                        │  SQLite / mock Snowflake  │
                                        │  connector (pandas)       │
                                        │  historical returns,      │
                                        │  factor indexes, mappings │
                                        └───────────────────────────┘

        All services orchestrated by a single docker-compose.yml
```

### 8.1 Layer Responsibilities

| Layer | Technology | Responsibility |
|---|---|---|
| **Data** | SQLite / mock Snowflake connector via pandas | Store historical asset-class returns, macro factor indexes, and asset-to-factor mappings. |
| **Analytics** | Pure Python (numpy/pandas, statsmodels/sklearn) | Portfolio return, volatility, VaR, factor loading regression, rebalancing optimization. Stateless and testable. |
| **Caching** | Redis | Cache expensive covariance matrices and factor-loading results keyed on inputs. |
| **API** | Flask | RESTful endpoints separating business logic from presentation. |
| **Presentation** | Streamlit *or* React + Plotly | Interactive dashboard, sliders, scenario dropdown, before/after and factor-exposure visualizations. |
| **Deployment** | Docker + docker-compose | One-command orchestration of backend, UI, and Redis. |

---

## 9. Data Model (Reference)

### 9.1 Asset Universe (illustrative)
| Asset ID | Name | Class |
|---|---|---|
| `SPY` | S&P 500 ETF | Equity |
| `IEF` | 7–10 Year Treasury ETF | Fixed Income (Rates) |
| `LQD` | Investment-Grade Corporate Bond ETF | Fixed Income (Credit) |
| `GLD` | Gold | Commodity |
| `DBC` | Broad Commodity Index | Commodity |

### 9.2 Core Tables / Frames
- **`asset_returns`** — `(asset_id, date, weekly_return)`
- **`factor_index`** — `(factor_name, date, index_value)` for Growth, Inflation, Rates, Credit.
- **`asset_factor_map`** — `(asset_id, factor_name, loading)` reference exposures.
- **`scenarios`** — `(scenario_id, name, start_date, end_date, description)`.
- **`portfolios`** — `(portfolio_id, asset_id, weight)`.

---

## 10. Tech Stack Mapping (Job Description Alignment)

This project was scoped to exercise the exact technologies named in the BlackRock IPS role:

| JD Requirement | How MacroShock Uses It |
|---|---|
| **Python** (must-have) | Entire analytics engine, API, and orchestration. |
| **SQL** (must-have) | Queries against SQLite / mock Snowflake data layer for returns and factor data. |
| **Snowflake** | Mock Snowflake connector pattern (pandas-backed) demonstrating the data-warehouse access model. |
| **Flask API** | RESTful service layer decoupling logic from UI. |
| **Streamlit** | Rapid, polished analytical dashboard option. |
| **Angular / React** | Alternative production-grade UI option with Plotly visualizations. |
| **Redis** | Caching of covariance matrices and factor-loading computations. |
| **Docker** | `docker-compose.yml` orchestrating all services with one command. |
| **TypeScript / UI** (plus) | Optional React + TS front-end path. |
| **Agile frameworks** | PRD-driven, story-based, iterative delivery blueprint (below). |
| **Financial data platforms** (Aladdin, Bloomberg, etc.) | Domain modeling of risk, attribution, and multi-asset stress testing mirrors Aladdin's core. |

---

## 11. Why This Resonates with BlackRock IPS

1. **Direct alignment with Aladdin's DNA** — Risk management, multi-asset portfolio construction, and stress testing are precisely what Aladdin is known for.
2. **Production architecture over scripting** — Redis caching of financial analytics and reusable Python modules signal enterprise engineering discipline, not throwaway data-science scripts.
3. **Business empathy** — The emphasis on *attribution* (understanding the drivers of risk) over a single return figure reflects how portfolio managers actually think. "The how is as important as the what."

---

## 12. 1-Day Execution Blueprint

### Block 1 — Core Data & Analytics Engine (Hours 1–3)
- Create a mock dataset of ~5 assets with weekly returns spanning several historical crisis windows.
- Write a pure Python module with standalone functions:
  - Portfolio return given a weights array.
  - Regression function computing portfolio sensitivity (Beta) to Growth and Inflation factors.
- Add volatility and VaR calculations.

### Block 2 — API & Caching Layer (Hours 4–6)
- Wrap the analytics module in a lightweight Flask app.
- Add a Redis connection; on `/stress-test`, build a cache key from weights + scenario. Return cached JSON if present, else compute → cache → return.
- Write unit tests for the analytics functions to demonstrate software-quality commitment.

### Block 3 — Interactive Interface & Containerization (Hours 7–9)
- Build a Streamlit or React UI with weight sliders and a scenario dropdown.
- Add clean visualizations (Plotly bar charts / exposure matrix) for shifting asset risk contributions.
- Write a `Dockerfile` and a `docker-compose.yml` linking the app service to a public Redis image so the whole project runs with `docker-compose up`.

---

## 13. Milestones & Deliverables

| Milestone | Deliverable | Acceptance Criteria |
|---|---|---|
| **M1: Analytics Core** | Tested Python module | Unit tests pass for returns, volatility, VaR, factor regression. |
| **M2: API + Cache** | Flask service with Redis | All three endpoints return valid JSON; cache hit returns < 200 ms. |
| **M3: UI + Deploy** | Dashboard + compose file | `docker-compose up` launches full stack; user completes a stress test end-to-end. |

---

## 14. Success Metrics

- **Functional completeness:** A user can define a portfolio, run all three scenarios, and receive attribution + a rebalance suggestion.
- **Explainability:** Every loss figure is accompanied by a factor-level breakdown.
- **Performance:** Cache-hit stress tests return in < 200 ms.
- **Reproducibility:** Fresh clone → `docker-compose up` → working app with zero manual config.
- **Code quality:** Analytics core has meaningful unit-test coverage and no coupling to the API/UI layers.

---

## 15. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep beyond 1 day | Incomplete demo | Freeze asset universe at ~5 and scenarios at 3; treat extras as stretch goals. |
| Overly complex factor model | Time overrun | Start with 2 factors (Growth, Inflation); add Rates/Credit only if time allows. |
| Redis adds setup friction | Reviewer can't run it | Ship it inside docker-compose; make the API degrade gracefully if Redis is down. |
| Mock data mistaken for real risk model | Misleading | Add clear disclaimers: illustrative, not investment advice or a certified model. |
| UI polish consuming build time | Weak core | Prioritize analytics + API correctness before visual refinement. |

---

## 16. Future Enhancements (Post-v1)

- Real historical data ingestion (e.g., FactSet / Bloomberg / Morningstar–style feeds).
- Monte Carlo synthetic scenario generation.
- Multi-factor optimization for rebalancing (constrained mean-variance).
- Live Snowflake connection replacing the mock connector.
- User accounts, saved portfolios, and scenario history.
- Authenticated multi-user deployment with role-based access.

---

## 17. Disclaimer

MacroShock is an educational and demonstrative project. It does not constitute investment advice, and its outputs are derived from illustrative/mock datasets and simplified models. It is not a certified or regulatory-grade risk system.
