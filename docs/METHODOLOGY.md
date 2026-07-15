# MacroShock — Quantitative Methodology

This document specifies every formula and data assumption used by the engine. It is the
single source of truth for the analytics layer. All symbols are defined once and reused.

> **Positioning:** MacroShock is a *portfolio consulting co-pilot*. It answers four questions
> a portfolio manager actually asks: **what breaks, why it breaks, which holding is to blame,
> and the single trade that reduces the pain** — using the same factor-based risk vocabulary
> as institutional risk platforms.

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| `n` | number of assets |
| `w` | column vector of portfolio weights, length `n`, with `Σ wᵢ = 1` |
| `r` | vector of asset returns for one period |
| `R_p` | portfolio return for one period, `R_p = wᵀr` |
| `Σ` | `n×n` covariance matrix of periodic asset returns |
| `σ_p` | portfolio volatility (standard deviation of `R_p`) |
| `P` | periods per year (weekly data ⇒ `P = 52`) |
| `K` | number of macro factors |
| `B` | `n×K` matrix of asset exposures (loadings) to factors |
| `s` | length-`K` vector of factor shocks (a scenario) |
| `Σ_F` | `K×K` covariance matrix of factor returns |

---

## 2. Portfolio return

Single-period portfolio return is the weighted sum of asset returns:

```
R_p = Σ_i w_i · r_i = wᵀ r
```

Compounded path over `T` periods with periodic returns `R_{p,t}`:

```
Cumulative(T) = Π_{t=1..T} (1 + R_{p,t}) − 1
```

---

## 3. Portfolio volatility

Variance of a linear combination of random variables:

```
σ_p² = wᵀ Σ w
σ_p  = sqrt(wᵀ Σ w)
```

Annualization (returns assumed serially independent):

```
σ_p,annual = σ_p · sqrt(P)
```

---

## 4. Value at Risk (VaR) and Expected Shortfall (CVaR)

### 4.1 Parametric (Gaussian) VaR
For confidence level `α` (e.g. 0.95), let `z_α = Φ⁻¹(α)` be the standard-normal quantile
(`z_0.95 = 1.6449`, `z_0.99 = 2.3263`). VaR is reported as a **positive loss**:

```
VaR_α = −(μ_p − z_α · σ_p) = z_α · σ_p − μ_p
```

For short horizons `μ_p` is often set to 0 (drift is negligible vs. volatility). The engine
exposes a `include_drift` flag; default `False`.

### 4.2 Expected Shortfall (CVaR) — Gaussian
Average loss *beyond* VaR:

```
CVaR_α = −μ_p + σ_p · φ(z_α) / (1 − α)
```

where `φ` is the standard-normal PDF. CVaR ≥ VaR always.

### 4.3 Historical VaR (provided as a cross-check)
Empirical `(1−α)` quantile of the realized portfolio return series, negated:

```
VaR_α^hist = −Quantile_{1−α}( {R_{p,t}} )
```

---

## 5. Factor loadings via OLS regression

Regress the portfolio (or asset) return series on the factor return series to obtain
factor betas. With design matrix `X` (a column of 1s for the intercept plus one column per
factor) and response `y` (return series):

```
β̂ = (Xᵀ X)⁻¹ Xᵀ y
```

The intercept is the annualizable alpha; the remaining coefficients are the factor betas
(`β_Equity, β_Rates, β_Credit, β_Commodity`). Goodness of fit reported as `R²`:

```
R² = 1 − SS_res / SS_tot
```

This is a standard multivariate linear factor model (Rosenberg/BARRA-style intuition).

---

## 6. Risk decomposition: Marginal & Component Contribution to Risk

This is the heart of *attribution* — it explains **which holding is to blame** for risk.

Because `σ_p = sqrt(wᵀΣw)` is homogeneous of degree 1 in `w`, Euler's theorem gives an
exact additive decomposition of total risk across holdings.

**Marginal Contribution to Risk (MCTR)** — sensitivity of portfolio vol to weight `i`:

```
MCTR_i = ∂σ_p/∂w_i = (Σ w)_i / σ_p
```

**Component Contribution to Risk (CCTR)** — the risk *owned* by holding `i`:

```
CCTR_i = w_i · MCTR_i = w_i · (Σ w)_i / σ_p
```

**Euler identity (must hold exactly):**

```
Σ_i CCTR_i = σ_p
```

**Percentage Contribution to Risk (PCTR):**

```
PCTR_i = CCTR_i / σ_p        (Σ_i PCTR_i = 1)
```

> **The insight that impresses:** a 40% *capital* weight can be 70% of the *risk*. MacroShock
> surfaces `PCTR_i` next to `w_i` so the divergence is visible at a glance.

---

## 7. Factor-based scenario stress testing

Rather than fabricating precise realized returns, MacroShock uses a **factor-shock model** —
the same approach institutional risk systems use. A scenario is a vector of macro factor
shocks `s`; each asset's scenario return is its exposure to those factors:

```
r_i^scenario = Σ_k B_{i,k} · s_k
Portfolio scenario return  R_p^scenario = wᵀ B s = Σ_i w_i · r_i^scenario
```

### 6.1 Factor definitions and asset exposure mechanics

| Factor `k` | Shock unit `s_k` | Exposure `B_{i,k}` mechanics |
|---|---|---|
| **Equity** | equity index total return (e.g. −0.34) | equity beta of the asset |
| **Rates** | change in yield `Δy` (decimal, e.g. +0.02 = +200bps) | `−EffectiveDuration_i` (bond price ≈ `−D·Δy + ½·C·Δy²`) |
| **Credit** | change in IG spread `Δspread` (decimal) | `−SpreadDuration_i` |
| **Commodity** | broad commodity index return | commodity beta of the asset |

Bond convexity term (`½·C·Δy²`) is included for the rates factor to keep large-shock
pricing accurate.

### 6.2 Factor sensitivities used (documented, defensible values)

| Asset | Equity β | Eff. Duration (yrs) | Spread Duration (yrs) | Commodity β |
|---|---|---|---|---|
| **SPY** (S&P 500 ETF) | 1.00 | 0.0 | 0.0 | 0.10 |
| **IEF** (7–10y Treasury) | −0.05 | 7.5 | 0.0 | 0.00 |
| **LQD** (IG corporate) | 0.20 | 8.4 | 8.4 | 0.00 |
| **GLD** (Gold) | −0.10 | 0.0 | 0.0 | 0.55 |
| **DBC** (Broad commodity) | 0.35 | 0.0 | 0.0 | 1.00 |

Durations reflect published effective durations for these fund categories; equity/commodity
betas are calibrated to long-run observed sensitivities. These are the *assumptions* — the
engine is transparent about them and they are stored in the data layer for easy revision.

### 6.3 Calibrated crisis scenarios

Scenario magnitudes are calibrated to documented market moves during each episode.

| Scenario | Equity | Rates `Δy` | Credit `Δspread` | Commodity | Rationale |
|---|---|---|---|---|---|
| **2008 GFC (acute)** | −45% | −150 bps | +400 bps | −50% | Flight to quality; IG spreads blew out; oil collapsed. |
| **2020 Liquidity Freeze** | −34% | −120 bps | +200 bps | −40% | S&P −33.9% Feb 19–Mar 23 2020; rates to record lows; oil crash. |
| **Synthetic 2026 Inflation Spike** | −15% | +200 bps | +150 bps | +30% | Yields rise, bonds fall, real assets rally. |

Sources are documented market history for the 2008 and 2020 episodes; the 2026 scenario is a
forward-looking synthetic stress. Values live in `scenarios` (data layer) and are editable.

---

## 8. Reverse stress testing (the differentiator)

Standard stress testing asks *"what happens in scenario X?"* **Reverse** stress testing flips
it: *"what scenario would make me lose L\*?"* — a technique mandated in institutional risk
frameworks.

The portfolio's sensitivity to factor shocks is the gradient vector:

```
g_k = ∂R_p/∂s_k = Σ_i w_i · B_{i,k}      ⇒   g = Bᵀ w
R_p^scenario = gᵀ s
```

We want the **most plausible** shock `s` that produces a target loss `L*` (i.e. `R_p = −L*`).
"Most plausible" = smallest Mahalanobis distance in factor space, `sᵀ Σ_F⁻¹ s` (the shock most
consistent with historical factor co-movement). Minimizing subject to the single linear
constraint `gᵀ s = −L*` has a closed-form solution (Lagrange multipliers):

```
s* = −L* · (Σ_F g) / (gᵀ Σ_F g)
```

This returns the single most-likely combination of Equity/Rates/Credit/Commodity shocks that
would deliver the specified loss — genuinely institutional, and cheap to evaluate once `Σ_F`
and `g` are known (which is why it is a good caching target).

---

## 9. Rebalancing recommendation

Rule-based and fully transparent (no black box):

1. Run the selected scenario; compute per-holding scenario P&L contribution `w_i · r_i^scenario`.
2. Identify the **dominant loss driver** holding (most negative contribution) and the
   **dominant factor** (largest `|w_i·B_{i,k}·s_k|` aggregated over holdings).
3. Identify the best **hedge asset**: the holding with the most favourable (least negative or
   positive) scenario return that also lowers portfolio vol (lowest `MCTR`).
4. Shift a capped fraction `δ` (default 15%) of weight from the loss driver to the hedge.
5. Recompute scenario drawdown and `σ_p`; report the **improvement** (Δ drawdown, Δ vol).

The recommendation is only surfaced if it strictly improves the scenario drawdown.

---

## 10. Investment commentary generation

Deterministic, template-driven narrative built from the computed numbers (no LLM required,
so it is reproducible and auditable). It weaves together: terminal drawdown, the dominant
factor, the worst-contributing holding with its `PCTR`, and the recommended trade with its
projected improvement — in the language a portfolio manager uses.

---

## 11. Caching rationale

The expensive objects are (a) the covariance matrices `Σ`, `Σ_F`, (b) the factor regression,
and (c) the reverse-stress solve. All are pure functions of
`(weights, scenario_id, confidence)`. MacroShock hashes those inputs into a deterministic
Redis key; on a hit it returns cached JSON in O(1). This is real caching of expensive
analytics, not decoration — and the API degrades gracefully to direct computation if Redis is
unavailable.

---

## 12. Data honesty statement

Live market feeds require a data licence and network access. For a self-contained,
reproducible showcase, MacroShock ships a **calibrated** historical return series generated to
reproduce the *documented* annualized volatilities and cross-asset correlations of these asset
classes (fixed random seed for reproducibility), while **scenario shocks are calibrated to
real crisis magnitudes** (Section 6.3). The data layer reads from SQLite via a mock Snowflake
connector, so swapping in a real warehouse table or a licensed feed (FactSet/Bloomberg-style)
is a one-file change. Nothing in the analytics assumes the data is synthetic.



---

# Part II — v2.0 Upgrades (rigor)

These sections extend the model to address the standard critiques of a naive stress tool:
Gaussian tails, self-validating data, scenario-agnostic attribution, static correlations,
missing risk factors, and unconstrained reverse stress.

## 13. Expanded factor set (6 factors)

The factor set is now **Equity, Rates, Credit, Commodity, Liquidity, FX**.

- **Liquidity** (return-space; down = funding/market stress). Loadings `liquidity_beta`
  capture assets hit by a dash-for-cash independent of credit spreads — e.g. IG corporates
  in March 2020 fell on *liquidity* as well as spread. Naming a scenario a "liquidity freeze"
  now has a factor to back it.
- **FX** (trade-weighted USD return; up = USD strength). Loadings `fx_beta` capture the haven
  bid for the dollar in crises and its drag on gold/commodities.
- **Gold** is re-classified as a **safe-haven / real-rates** asset (small commodity loading,
  negative FX loading), not a pure commodity — its crisis behaviour is monetary, not cyclical.

Scenario asset return generalizes to `r_i = Σ_k B_{i,k} s_k` over all six factors (bond
convexity retained on the Rates term).

## 14. Regime-switching, fat-tailed data generation

The historical series is generated from a **two-regime** model:

- **Calm** and **crisis** regimes each have their **own correlation matrix**; crisis
  correlations amplify toward the risk-off cluster (contagion). This reproduces the empirical
  fact that diversification fails precisely when it is needed.
- Factor innovations are **Student-t** (fat tails), with fewer degrees of freedom in the
  crisis regime (`ν=4`) than in calm (`ν=8`), scaled so the target covariance is preserved.
- Idiosyncratic noise is sized so the factor regression **R² is realistic (~0.7–0.85)**, not
  the ~0.99 that a noiseless factor construction would produce. A near-1.0 R² is a red flag
  for planted/circular data; we deliberately avoid it.

Crisis correlation matrices are projected to the **nearest positive-semidefinite** matrix
(eigenvalue clipping) before use, so Cholesky sampling is always valid.

## 15. Robust covariance (Ledoit–Wolf shrinkage)

The sample covariance is noisy when `T` is not ≫ `n`, and that noise flows straight into
MCTR. We shrink toward a scaled-identity target `F = m·I`:

```
Σ_shrunk = δ·F + (1−δ)·S
```

with the optimal intensity `δ` estimated per Ledoit & Wolf (2004). The intensity is reported
in `/api/meta` so the degree of shrinkage is transparent.

## 16. Fat-tailed risk measures

Gaussian VaR is retained as a baseline but is explicitly shown alongside three tail-aware
measures so its optimism is visible:

- **Historical VaR / CVaR** — empirical `(1−α)` quantile / tail mean of realized returns.
- **Cornish–Fisher (modified) VaR** — corrects the Gaussian quantile for skew `S` and excess
  kurtosis `K`:
  ```
  z_cf = z + (z²−1)/6·S + (z³−3z)/24·K − (2z³−5z)/36·S²
  VaR  = −(μ + σ·z_cf)
  ```
- **Student-t VaR** — parametric VaR under a t-distribution (`ν=5`), quantile rescaled by
  `sqrt((ν−2)/ν)` so its variance equals `σ_p²`.

## 17. Regime-conditional risk attribution

The critique "MCTR is the same regardless of scenario" is addressed by computing risk
contributions under **both** the calm (full-sample, shrunk) covariance **and** a
**crisis-regime** covariance estimated on empirically-detected high-stress weeks
(`regime.py`: weeks whose standardized-return norm exceeds the 85th percentile). The UI shows
capital %, calm risk %, and crisis risk % side by side, and the commentary reports the
**shift** in a holding's risk share from calm to crisis — the effect a single-regime model
cannot see.

## 18. Constrained & top-k reverse stress

The closed-form minimum-Mahalanobis solution is retained as a baseline, but the primary
result is now a **bounded** solve:

```
minimize   sᵀ Σ_F⁻¹ s
subject to gᵀ s = −L*,   lb ≤ s ≤ ub      (SLSQP)
```

Per-factor bounds (e.g. credit spreads cannot collapse) stop the "most plausible" answer from
returning economically nonsensical shock combinations. We also return the **top-k
single-factor narratives** — the pure equity/credit/rates/… paths to the same loss, each with
its own plausibility (Mahalanobis) score — because a PM thinks in terms of "which one thing
could do this."

## 19. Backtest validation (out-of-sample)

The factor-shock engine's **predicted** asset returns are compared against **realized**
documented returns for the 2008 and 2020 windows (`realized_crisis_returns`, loaded
independently of the model). Per-asset and per-portfolio errors plus MAE/RMSE are reported via
`/api/backtest`. This is the difference between validating the model against reality and
validating it against itself.

---

## 20. Limitations (read this before trusting a number)

- **Data are calibrated/synthetic.** Live feeds need a licence and network access. The weekly
  history is generated to match documented volatilities, fat tails and regime behaviour; the
  crisis *magnitudes* and *realized* returns are calibrated to documented events. This is a
  reproducible demonstration, not a fitted production model. The data layer is one file from a
  real warehouse/feed.
- **Exposures are static within a regime.** Betas/durations do not continuously vary with the
  state of the world; we approximate regime dependence with a two-state calm/crisis split, not
  a full time-varying (e.g. DCC-GARCH) model.
- **Reverse stress uses a Gaussian plausibility metric** (Mahalanobis). Tail dependence
  (copulas) would make extreme joint moves look *more* plausible than this suggests.
- **Scenario shocks are instantaneous** (no path, no compounding); the 1-week VaR and the
  multi-month scenario drawdown are different horizons and are labelled as such in the UI.
- **Not investment advice; not a regulatory-grade risk system.**



---

# Part III — v3.0 Upgrades (closing the review loopholes)

This part addresses the specific critiques a quant reviewer raises against v2: circular
backtest, planted-then-discovered tails, selection-biased regime detection, regime-
inconsistent reverse stress, unidentified collinear factors, i.i.d. crises, an identity
shrinkage target, a heuristic rebalance, missing error bars, and no path to real data.

## 21. Out-of-sample backtest with skill (was: circular calibration check)

The v2 backtest compared hand-calibrated shocks to the realized returns they were calibrated
to — a consistency check, not a forecast. v3 adds a **leave-one-crisis-out** test:

1. **Implied shocks:** invert one crisis's realized returns into factor space,
   `s = argmin_s ‖B_sub s − r‖` (least squares through the exposure matrix).
2. Use shocks implied from the **other** crises to predict the **held-out** crisis; its
   realized returns never enter the prediction.
3. Score against three naive benchmarks — **predict-zero**, **repeat-last-crisis**, and
   **equity-factor-only** — and report a **skill ratio** `1 − RMSE_model / RMSE_benchmark`.

Positive skill means the factor model genuinely beats the naive rule. With five crisis
windows (GFC, Euro 2011, dot-com, COVID, 2022) this is indicative, not conclusive, and is
labelled as such. The in-sample check is retained but explicitly marked "not a skill test."

## 22. Chi-square regime detection (was: top-x% selection bias)

A top-15% quantile rule flags 15% of weeks as "crisis" on *any* data, including pure calm
noise — selection bias. v3 uses a **statistical test**: the squared Mahalanobis distance of a
week's standardized returns is `~ χ²(n)` under multivariate normality. Weeks exceeding the
`χ²(n)` critical value at level `p` (default 0.99) are crises. On genuinely calm/normal data
this flags only ~`(1−p)` of weeks (almost none); a regime is detected only if the data has
one. The level relaxes step-wise only if too few weeks are captured to estimate a covariance,
and the achieved rate is reported.

## 23. Persistent (Markov) crisis generation (was: i.i.d. crises)

Crises cluster (volatility clustering). v3 generates the regime path as a **2-state Markov
chain** with `P(crisis→crisis)=0.80` (≈5-week average crisis spells), with `P(calm→crisis)`
solved so the stationary crisis probability equals the target 12%. This produces contiguous
crisis episodes rather than isolated single-week spikes.

## 24. Constant-correlation shrinkage (was: identity target)

Shrinking toward a scaled identity pulls correlations to zero — backwards for a tool whose
thesis is that correlations matter. v3 uses the **Ledoit–Wolf (2003) constant-correlation
target**: each asset keeps its own variance and all pairwise correlations shrink toward the
average sample correlation. Optimal intensity `δ = κ/T` with the full `π, ρ, γ` estimators.

## 25. Regime-consistent reverse stress (was: calm covariance for a crisis question)

Reverse stress now measures shock plausibility (Mahalanobis distance) against the
**crisis-regime factor covariance**, the same regime used for risk attribution — so a
crisis-sized shock is judged against crisis-time co-movement, not calm-blended co-movement.

## 26. Multicollinearity diagnostics (was: unidentified collinear factors)

Adding Liquidity/FX created collinearity (crisis Credit–Liquidity ≈ −0.8). v3 reports, per
factor, the **Variance Inflation Factor** (diagonal of the inverse correlation matrix) and the
**condition number** of the factor set, so unstable/under-identified coefficients are visible.
A **ridge** option (`λ>0`, intercept unpenalized, sandwich standard errors) is available to
stabilize betas.

## 27. Statistical tail evidence (was: asserted fat tails)

Instead of asserting fat tails, v3 reports the **Jarque–Bera** normality test (statistic +
p-value), an **MLE-fitted Student-t dof** used to parameterize the t-VaR, and a
**Cornish–Fisher validity flag** (whether the CF quantile map is monotone in the tail; if not,
the UI defers to historical VaR). The evidence for non-normality is now measured, not claimed.

## 28. MCTR confidence intervals (was: false precision)

Risk contributions are reported with **block-bootstrap** percentile intervals: overlapping
blocks of the return history are resampled (preserving short-run autocorrelation), PCTR is
recomputed on each resample, and a 90% interval per holding is reported alongside the point
estimate.

## 29. Constrained-optimization rebalance (was: greedy single shift)

The mitigation is now a genuine constrained optimization (SLSQP):
`minimize wᵀΣ_crisis w` subject to `Σw=1`, long-only, a per-asset turnover cap, and
`rᵀw ≥ rᵀw₀` (scenario drawdown not worsened). It reports the optimized weights, the
volatility change, and the turnover.

## 30. Real-data path (the one residual)

`data/providers.py` has two real-data loaders: `CsvReturnsProvider` (export real returns to
CSV and point the engine at it) and an import-guarded `YFinanceReturnsProvider` (live data
when a network and `yfinance` are available). The default synthetic data reads the warehouse
directly, so no loader is needed for it. Swapping data sources requires no analytics change.

This is now **wired into the seed** via `python -m data.seed --source {synthetic,csv,yahoo}`:

- `synthetic` (default) — the reproducible two-regime generator.
- `csv --csv PATH` — a weekly-returns file (`date,SPY,IEF,…`).
- `yahoo --start YYYY-MM-DD` — live download of the 13-asset universe via `yfinance`.

For real sources, **factor returns are derived from realized asset returns by projection
onto the exposure matrix**: per week `f_t = pinv(B) a_t`. This produces native-unit factor
histories (yield/spread changes, index returns) consistent with the documented loadings,
rather than scraping unreliable free proxies for credit-spread or liquidity factor levels —
the same least-squares inversion the backtest uses for implied shocks. Any failure (offline,
missing `yfinance`, malformed CSV) **degrades gracefully to synthetic** and records the fact.
The active source and window are stored in `dataset_meta` and surfaced at `/api/meta` and
`/health` (`data_source`), so a consumer always knows whether numbers are live or simulated.

---

## 31. Limitations (v3 — what genuinely remains)

Most v2 limitations are now addressed (regimes persist and are detected statistically; tails
are tested; attribution has error bars; reverse stress is regime-consistent; the backtest is
out-of-sample; multicollinearity is disclosed). What remains:

- **The shipped dataset is still synthetic.** There is no network in the build environment to
  pull a licensed feed, so the history is calibrated/simulated (to documented vols, fat tails,
  and regime behaviour) and crisis magnitudes/realized returns are calibrated to documented
  events. This is the honest ceiling of a self-contained demo. It is **one provider swap** from
  real data (`CsvReturnsProvider` / `YFinanceReturnsProvider`), and no analytics assume the
  data is synthetic.
- **Only five crisis windows** exist for the out-of-sample test, so the skill score is
  indicative, not statistically conclusive.
- **Exposures are static within a regime** (two-state calm/crisis), not a continuous
  time-varying (DCC-GARCH) model.
- **Not investment advice; not a regulatory-grade risk system.**



---

# Part IV — v3.1 Recalibration & reverse-stress hardening

## 32. Factor betas recalibrated to realized crisis returns

The v3.0 betas contained double-counting (an asset hit by *both* its spread duration and a
large liquidity beta) and mislabelled gold as a commodity, producing crisis predictions with
no historical precedent (e.g. investment-grade credit at −41%) — which the backtest correctly
exposed. v3.1 recalibrates the exposure matrix so the factor model reproduces documented
realized crisis returns:

- **Cross-loadings minimized.** Each asset loads mainly on its primary factor(s); equity is
  the equity factor (no extra commodity/liquidity pile-on), so SPY ≈ the equity shock.
- **LQD** credit (spread duration 6.0) and a modest liquidity beta (0.30) — no longer
  double-counted — give ≈ −13% in both crises (vs realized −12%/−14%), not −41%.
- **Gold reclassified as a safe haven:** negative equity beta (−0.18) and negative FX beta
  (−0.20), zero commodity beta. It now correctly **rises** in 2008 (≈ +3-5%) and is ≈ flat in
  2020 — the hedge behaviour a client expects.
- **Scenario shocks moderated** (e.g. 2008 credit +300bps rather than +400bps) so linear
  factor pricing stays within realistic magnitudes.

Result: in-sample per-asset backtest **MAE ≈ 1%** (was ~17%). The betas remain hand-set
structural assumptions (durations from published data; loadings calibrated to five crises), not
statistically estimated — stated plainly, not dressed up as measurements.

## 33. Reverse-stress bounding, feasibility and honest language

- **Single-factor paths are bounded/flagged.** Forcing an entire loss through one factor can
  imply an impossible move (e.g. a commodity index down >100%); such paths are now marked
  **infeasible within bounds** and never presented as plausible.
- **Reachability.** If no factor combination within plausible bounds reaches the target loss,
  the tool reports the **worst plausible loss** instead of returning an absurd shock, and says
  the target is unreachable (a reassuring result).
- **"Plausible" vs "least-implausible".** The primary shock is only called "most plausible"
  when its Mahalanobis distance ≤ 3σ; beyond that it is labelled "least-implausible" and, past
  ~4σ, explicitly flagged as effectively unreachable rather than framed as a recommendation.

## 34. UI honesty fixes

Tail-risk copy is now data-driven (it names the actually-largest VaR estimate and notes that
positive skew can pull Cornish-Fisher *below* Gaussian — the methods need not be monotone).
**CVaR / Expected Shortfall** (Gaussian and historical) is surfaced alongside VaR. The
target-loss slider uses integer-percent units. Model outputs avoid false precision, and the
deploy chrome is hidden to keep the framing as an analytical tool, not a capital-backed system.
