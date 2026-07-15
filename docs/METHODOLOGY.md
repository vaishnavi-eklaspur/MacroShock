# MacroShock — Quantitative Methodology

This document specifies every formula and data assumption used by the engine. It is the
single source of truth for the analytics layer. All symbols are defined once and reused.

> **Positioning:** MacroShock is a *portfolio consulting co-pilot*. It answers four questions
> a portfolio manager actually asks: **what breaks, why it breaks, which holding is to blame,
> and the single trade that reduces the pain** — using the same factor-based risk vocabulary
> as institutional platforms (Aladdin-style).

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
