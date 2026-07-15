# MacroShock — Scaling PRD: From Demonstration to Capital-Grade Risk System

| Field | Value |
|---|---|
| **Author** | Vaishnavi Eklaspur |
| **Status** | Vision / Draft v1.0 |
| **Audience** | Investment & Portfolio Solutions (IPS) Technology + Risk |
| **Purpose** | Define what it takes to move MacroShock from a correct, honest *framework* to a model a desk would trust with real capital. |

---

## 0. Framing: what "trust with capital" actually means

The current build is a **correct and honest framework**, but it is not trustworthy with money for three structural reasons, all disclosed in `docs/METHODOLOGY.md`:

1. **The data is synthetic** — it has never touched a real price.
2. **The factor betas are hand-calibrated to two crises**, so the backtest is circular (a fitting residual, not out-of-sample skill).
3. **There is no model-risk governance** — no independent validation, no controls, no audit trail, no monitoring.

"Capital-grade" is not a better chart. It is the property that an **independent validator, a risk committee, and a regulator** would each sign off that the model's numbers can inform position sizing. This PRD is the path to that property. It is organized as eight workstreams and a phased plan.

> **North-star definition of 10/10 trustworthy:** *An independent model-validation team, using data and code we did not hand them, can reproduce every number, stress it, and conclude the model's risk estimates are statistically sound, well-calibrated out-of-sample, and safe to use within a documented scope — and a monitoring system will page us the moment that stops being true.*

---

## 1. Goals & success criteria (measurable)

| # | Goal | Success metric |
|---|---|---|
| G1 | Real, point-in-time data | 20+ years of licensed daily data across all instruments; zero look-ahead in any backtest (point-in-time snapshots). |
| G2 | Estimated (not fitted) model | Factor betas estimated from data with published standard errors; no parameter hand-tuned to a validation period. |
| G3 | Genuine out-of-sample skill | Positive, statistically significant skill vs. benchmarks across ≥10 independent stress episodes, on a walk-forward basis. |
| G4 | Calibrated risk | VaR/ES backtests pass Kupiec (unconditional) and Christoffersen (conditional) coverage tests at 95% and 99%. |
| G5 | Independent validation sign-off | Model passes an SR 11-7-style validation with documented limitations and an approved usage scope. |
| G6 | Production reliability | 99.9% API availability; p99 latency < 500 ms warm; full reproducibility from a versioned data + code + config hash. |
| G7 | Governed lifecycle | Every result is auditable to its inputs; drift monitoring triggers revalidation; change control on models. |

---

## 2. Non-goals (explicit scope boundaries)

- **Not** an execution/OMS platform — it informs sizing, it does not place orders.
- **Not** an alpha/return-forecasting engine — it is a *risk* model (dispersion, tails, attribution), and conflating the two is a common failure.
- **Not** a replacement for a firm's authoritative risk system (e.g., Aladdin) — position it as a complementary scenario/attribution lens, or as a validated internal challenger model.
- **Not** a fully automated decision-maker — a human with override authority is always in the loop.

---

## 3. Guiding principles

1. **Separation of calibration and validation.** Parameters are estimated on one period and tested on a disjoint one. No parameter is ever tuned to improve a number it is later judged by. (This is the single flaw that most limits the current build.)
2. **Uncertainty is a first-class output.** Every risk number ships with a confidence interval or a stated estimation error. Point estimates without error bars are banned.
3. **Conservatism under ignorance.** Where the model is extrapolating beyond its data (large shocks, unseen regimes), it must widen intervals and flag low confidence, not extrapolate linearly with false precision.
4. **Everything is reproducible and auditable.** A result = f(data snapshot hash, code version, config version). No exceptions.
5. **The model has a documented scope of validity**, and refuses (or loudly caveats) outside it.

---

## 4. Workstreams

### WS1 — Data foundation (the precondition for everything)

The model is only as trustworthy as its data. This is the largest and most important workstream.

- **Licensed market & macro data:** equities/ETFs, rates curves, credit spreads (by rating/sector), FX, commodities, volatility surfaces — from Bloomberg / Refinitiv / FactSet / ICE and macro from FRED/central banks. Replace the `CsvReturnsProvider` stub with governed connectors.
- **Point-in-time / bitemporal store:** every datum stamped with *as-of* and *knowledge* dates so backtests use only what was known then (no look-ahead, no survivorship bias, no restated-index contamination). This is non-negotiable for credible backtesting.
- **Corporate-actions, holidays, and instrument-lifecycle handling;** delisted/defaulted instruments retained (survivorship).
- **Data-quality gates:** automated checks for staleness, spikes, gaps, unit errors, and cross-source reconciliation; quarantine + alerting on breach.
- **Data lineage & catalog:** every field traceable to source, with license terms and redistribution rules enforced.
- **Warehouse at scale:** Snowflake (the mock connector becomes real), partitioned by date/instrument; a feature store for derived factor series.

**Exit criteria:** 20+ years, multi-asset, point-in-time, quality-gated, lineage-tracked, reproducible by snapshot hash.

### WS2 — Model methodology (estimate, don't assert)

- **Estimated factor exposures:** betas/durations/spread-durations estimated via rolling/EWMA regressions and issuer-level analytics, with standard errors — replacing hand-set constants. Handle multicollinearity with a properly identified factor set (orthogonalization / hierarchical factors / statistical factors via PCA-on-residuals), reported VIF/condition monitoring.
- **Proper regime modeling:** replace the two-state heuristic with a **Markov-switching / hidden-Markov model** on volatility & correlation, or **DCC-GARCH** for time-varying correlation. Regimes become estimated states with transition probabilities, not a chi-square cutoff.
- **Fat tails done right:** **Extreme Value Theory (POT/GPD)** for tail quantiles and a **t-copula / vine copula** for tail *dependence* — so joint extreme moves are modeled, not assumed Gaussian. Reverse-stress plausibility uses the copula, not Mahalanobis.
- **Scenario library, governed:** historical (many episodes, not two), hypothetical, and regulatory (CCAR/EBA-style) scenarios, each versioned and reviewed. Scenario shocks are *derived* from history or committee-approved, and are checked for internal consistency against the estimated covariance (the current build's scenarios would flag as many-sigma under its own metric — that inconsistency must be resolved).
- **Uncertainty everywhere:** parameter uncertainty (bootstrap/Bayesian), propagated into every VaR/ES/attribution output as intervals.
- **Liquidity & non-linearity:** add liquidity-adjusted VaR, option/convexity via full revaluation (not just duration+convexity), and horizon scaling that respects autocorrelation.

**Exit criteria:** no hand-tuned parameter; every exposure estimated with error bars; regimes and tails modeled with recognized methods; scenarios governed and internally consistent.

### WS3 — Validation & backtesting (the part that earns trust)

- **Strict train/validate/test discipline:** walk-forward / expanding-window estimation; parameters never see the evaluation window. This directly fixes the circular-calibration flaw.
- **Coverage backtesting:** Kupiec POF and Christoffersen independence/conditional-coverage tests for VaR at 95%/99%; ES backtests (Acerbi-Székely). Traffic-light (Basel) exception counting.
- **Many regimes:** evaluate across ≥10 documented stress episodes and rolling out-of-sample windows — two crises is an anecdote, not a backtest.
- **Benchmarking against challengers:** historical simulation, filtered historical simulation, RiskMetrics EWMA, and a Monte-Carlo full-reval baseline. The model must earn its complexity by beating simpler methods on a statistically significant basis.
- **Attribution validation:** decomposed P&L reconciles to realized P&L within tolerance across the sample.
- **Sensitivity & robustness:** perturb inputs/assumptions; confirm no discontinuities or implausible outputs; adversarial scenarios.

**Exit criteria:** documented, reproducible validation pack showing calibrated coverage and significant out-of-sample skill across many regimes.

### WS4 — Model Risk Management & governance (SR 11-7)

- **Independent validation:** a team that did not build the model reproduces, challenges, and signs off; findings tracked to closure.
- **Model documentation:** conceptual soundness, assumptions, data, limitations, and *approved scope of use* — a living document, versioned.
- **Model inventory & tiering:** registered in the firm's model inventory with a materiality tier and a mandated revalidation cadence.
- **Change control:** any model/data/scenario change goes through review, versioning, and re-approval; `MODEL_VERSION` becomes a governed artifact, not a string I bumped.
- **Effective challenge:** documented reviewer challenge and responses (the three hostile reviews in this project's history are a template for that culture).

**Exit criteria:** validation sign-off, inventory registration, documented usage scope, and a revalidation schedule.

### WS5 — Production platform (reliability, scale, security)

- **Reliability:** 99.9% availability, health checks, graceful degradation, DR/backup, no single points of failure. (Redis-optional degradation already models this instinct.)
- **Performance & scale:** vectorized/distributed compute (Ray/Spark) for Monte-Carlo and bootstrap; pre-computed nightly risk with intraday incremental updates; p99 < 500 ms warm.
- **Reproducibility:** every response tagged with `{data_snapshot_hash, code_version, config_version}`; any historical result re-derivable exactly.
- **Security:** authN/authZ (SSO, RBAC), secrets management, encryption in transit/at rest, dependency scanning, no PII/entitlement leakage; penetration-tested.
- **Observability:** metrics/logs/traces, latency and error SLOs, alerting.
- **CI/CD with gates:** tests + `verify_math` + validation smoke must pass to deploy; infrastructure-as-code.

**Exit criteria:** SLOs met in production; reproducibility and security controls audited.

### WS6 — Explainability, human oversight & controls

- **Attribution to the trade level**, with confidence intervals and plain-language narrative (the commentary engine, extended and validated).
- **Human-in-the-loop:** recommendations are advisory; a portfolio manager with authority reviews and can override, with the override logged and justified.
- **Guardrails:** the model refuses or loudly caveats outside its validated scope (e.g., instruments/regimes it wasn't estimated on); no silent extrapolation.
- **"Show your work":** every headline number drills down to inputs, parameters, and their vintage.

**Exit criteria:** every output is explainable, bounded, overridable, and logged.

### WS7 — Monitoring, drift & lifecycle

- **Ongoing performance monitoring:** live VaR exceptions vs. expected, ES backtest, attribution reconciliation — dashboards + alerts.
- **Drift detection:** input distribution drift, parameter instability, and backtest degradation trigger automatic revalidation flags.
- **Scheduled recalibration** with change control; champion/challenger running in parallel before promotion.
- **Incident playbooks:** what happens when the model breaks or a data feed fails (fallback to a simpler validated method).

**Exit criteria:** automated monitoring that pages on miscalibration; a documented recalibration and incident process.

### WS8 — Compliance & audit

- **Full audit trail:** who ran what, with which data/model version, and what decision followed. Immutable logs.
- **Regulatory alignment:** SR 11-7 (US), TRIM/EBA (EU) model-risk expectations; data-licensing compliance for redistribution.
- **Access & entitlements:** portfolio-level entitlements so users only see permitted books.

**Exit criteria:** audit-ready; passes internal audit and a data-license review.

---

## 5. Phased delivery (crawl → walk → run)

| Phase | Theme | Duration | Key deliverables | Trust level |
|---|---|---|---|---|
| **P0 (today)** | Honest framework | done | Correct math, disclosed limits, one synthetic dataset | Demo (5/10) |
| **P1 — Crawl** | Real data + estimated model | ~1 quarter | WS1 point-in-time store; WS2 estimated betas with errors; walk-forward backtest on real data | Internal research (6.5) |
| **P2 — Walk** | Validated methodology | ~2 quarters | WS2 regimes/EVT/copula; WS3 coverage tests + challenger benchmarks across many regimes; uncertainty everywhere | Validation-ready (8) |
| **P3 — Run** | Governed production | ~2 quarters | WS4 independent validation sign-off; WS5 production SLOs/security; WS6 oversight; WS7 monitoring; WS8 audit | **Capital-grade (10)** |

Trust is earned in this order — data, then estimation, then validation, then governance. Skipping any step forfeits the score.

---

## 6. Definition of Done — the 10/10 checklist

A number from MacroShock may inform capital allocation only when **all** hold:

- [ ] Every input is real, point-in-time, quality-gated, and lineage-tracked.
- [ ] No parameter was tuned on data used to validate it (calibration ⟂ validation).
- [ ] VaR/ES pass Kupiec + Christoffersen coverage at 95% & 99% on out-of-sample data.
- [ ] The model shows significant skill vs. simpler challengers across ≥10 regimes.
- [ ] Every risk number carries an uncertainty interval.
- [ ] An independent validation team has reproduced and signed off, with a documented scope of use.
- [ ] Production meets availability/latency SLOs and full reproducibility.
- [ ] Live monitoring pages on miscalibration/drift; recalibration is governed.
- [ ] Every result is auditable to its inputs, model version, and the human who acted on it.

---

## 7. Team & roles (what it takes)

Quant researchers (model methodology), model-validation quants (independent), data engineers (point-in-time platform), platform/SRE engineers (production), a product owner, and — critically — **risk governance / model-risk management** ownership. This is a team effort spanning a year; no individual ships capital-grade alone.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Data licensing cost/complexity | Start with one asset class end-to-end; prove value before breadth. |
| Overfitting under limited crisis history | Walk-forward discipline, challenger benchmarks, EVT for the tail, wide intervals under ignorance. |
| False confidence from a slick UI | Uncertainty-first outputs; scope guardrails; the model refuses to extrapolate silently. |
| Scope creep into return forecasting | Hard non-goal; risk model only. |
| "Looks done" ≠ validated | Independent validation is a gate, not a formality. |

---

## 9. Closing

The current project's greatest asset is not its code — it is its **honesty about its own limits**. Capital-grade is that same honesty, industrialized: real data instead of synthetic, estimated parameters instead of hand-fit, out-of-sample validation instead of a circular residual, and independent governance instead of self-assessment. Deliver the eight workstreams in the crawl-walk-run order and MacroShock becomes not "another portfolio project," but a documented, validated, monitored risk model a desk could actually lean on.
