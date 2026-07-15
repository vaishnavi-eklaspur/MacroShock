"""MacroShock dashboard (Streamlit).

A portfolio consulting co-pilot: what breaks, why (regime-aware), which holding is to blame
(with confidence intervals), how fat the tail is (with a normality test), the optimized trade
that helps, reverse stress in the crisis regime, and an out-of-sample backtest with a skill
score against naive benchmarks.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:5000")
st.set_page_config(page_title="MacroShock", page_icon="⚡", layout="wide")


@st.cache_data(ttl=60)
def api_get(path: str) -> dict:
    r = requests.get(f"{API_BASE}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: dict) -> dict:
    r = requests.post(f"{API_BASE}{path}", json=payload, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("error", r.text))
    return r.json()


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


try:
    assets = api_get("/api/assets")["assets"]
    scenarios = api_get("/api/scenarios")["scenarios"]
    meta = api_get("/api/meta")
except Exception as exc:
    st.error(f"Cannot reach the MacroShock API at {API_BASE}. Is the backend running? ({exc})")
    st.stop()

tickers = [a["ticker"] for a in assets]
asset_names = {a["ticker"]: a["name"] for a in assets}

st.title("⚡ MacroShock")
st.caption("A portfolio consulting co-pilot — what breaks, why it breaks, which holding is to "
           "blame, and the single trade that reduces the pain.")

# ---------------------------------------------------------------- sidebar
st.sidebar.header("Portfolio")
default_weights = {"SPY": 40, "IEF": 20, "LQD": 20, "GLD": 10, "DBC": 10}
raw = {t: st.sidebar.slider(f"{t} — {asset_names[t]}", 0, 100, default_weights.get(t, 0), 1)
       for t in tickers}
total = sum(raw.values())
if total == 0:
    st.sidebar.error("Allocate some weight to at least one asset.")
    st.stop()
weights = {t: v / total for t, v in raw.items()}
st.sidebar.metric("Total allocation", f"{total}%", help="Weights are normalized to 100%.")

st.sidebar.header("Scenario")
scenario_labels = {s["scenario_id"]: s["name"] for s in scenarios}
scenario_id = st.sidebar.selectbox("Stress scenario", list(scenario_labels.keys()),
                                   format_func=lambda k: scenario_labels[k])
confidence = st.sidebar.select_slider("VaR confidence", [0.90, 0.95, 0.975, 0.99], value=0.95)

st.sidebar.divider()
rg = meta["regime"]
st.sidebar.caption(f"Model v{meta['model_version']} · {meta['shrinkage_target'].split('(')[0].strip()} "
                   f"shrinkage δ={meta['shrinkage_intensity']:.2f}")
st.sidebar.caption(f"Regime: {rg['n_crisis_weeks']}/{rg['n_weeks']} crisis weeks detected, "
                   f"vol {rg['vol_amplification']:.1f}× calm")

tab_stress, tab_reverse, tab_backtest, tab_model = st.tabs(
    ["Stress test", "Reverse stress", "Backtest (out-of-sample)", "Model & diagnostics"])

# ================================================================ STRESS TEST
with tab_stress:
    try:
        result = api_post("/api/portfolio/stress-test",
                          {"weights": weights, "scenario_id": scenario_id, "confidence": confidence})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()

    scenario = result["scenario"]
    riskd = result["risk"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Scenario drawdown", pct(result["portfolio_drawdown"]),
              help="Instantaneous shock, not annualized.")
    c2.metric(f"Historical VaR ({confidence:.0%}, 1wk)", pct(riskd["var"]["historical"]))
    c3.metric(f"Gaussian VaR ({confidence:.0%}, 1wk)", pct(riskd["var"]["gaussian"]))
    c4.metric("Annualized vol", pct(riskd["volatility_annual"]))
    tag = "cache hit" if result.get("cache_hit") else "computed"
    st.caption(f"**{scenario['name']}** — {scenario['description']}  ·  {tag} in "
               f"~{round(result.get('latency_ms', 0))} ms")

    st.subheader("🧭 Investment commentary")
    st.info(result["commentary"])

    left, right = st.columns(2)
    with left:
        st.subheader("Factor P&L attribution")
        fp = result["factor_pnl_attribution"]
        fdf = pd.DataFrame({"Factor": list(fp.keys()), "P&L %": [v * 100 for v in fp.values()]})
        fig = px.bar(fdf, x="Factor", y="P&L %", color="P&L %", color_continuous_scale="RdYlGn")
        fig.update_layout(showlegend=False, coloraxis_showscale=False, height=360)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Risk share: calm vs. crisis regime")
        rc = result["risk_contribution"]
        comp = pd.DataFrame({
            "Ticker": tickers,
            "Capital %": [weights[t] * 100 for t in tickers],
            "Risk % (calm)": [rc["calm_percentage"][t] * 100 for t in tickers],
            "Risk % (crisis)": [rc["stressed_percentage"][t] * 100 for t in tickers],
        })
        fig2 = go.Figure()
        fig2.add_bar(name="Capital %", x=comp["Ticker"], y=comp["Capital %"])
        fig2.add_bar(name="Risk % (calm)", x=comp["Ticker"], y=comp["Risk % (calm)"])
        fig2.add_bar(name="Risk % (crisis)", x=comp["Ticker"], y=comp["Risk % (crisis)"])
        fig2.update_layout(barmode="group", height=360)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Tail check: VaR under different distributional assumptions")
    var = riskd["var"]
    jb = riskd.get("normality_test", {"p_value": float("nan"), "normal_rejected": False})
    dof = riskd.get("fitted_student_t_dof", 5.0)
    vardf = pd.DataFrame({
        "Method": ["Gaussian", f"Student-t (fitted ν={dof:.1f})", "Cornish-Fisher", "Historical"],
        f"1-week VaR ({confidence:.0%})": [var["gaussian"] * 100, var["student_t"] * 100,
                                            var["cornish_fisher"] * 100, var["historical"] * 100],
    })
    figv = px.bar(vardf, x="Method", y=f"1-week VaR ({confidence:.0%})", color="Method")
    figv.update_layout(showlegend=False, height=320)
    st.plotly_chart(figv, use_container_width=True)

    cvar = riskd.get("cvar", {})
    cv1, cv2 = st.columns(2)
    cv1.metric(f"Gaussian CVaR / ES ({confidence:.0%})", pct(cvar.get("gaussian", float("nan"))),
               help="Expected loss conditional on breaching VaR (tail-conditional).")
    cv2.metric(f"Historical CVaR / ES ({confidence:.0%})", pct(cvar.get("historical", float("nan"))))

    m = riskd["moments"]
    normal_txt = "REJECTS normality" if jb.get("normal_rejected") else "cannot reject normality"
    labels = {"gaussian": "Gaussian", "student_t": "Student-t", "cornish_fisher": "Cornish-Fisher",
              "historical": "Historical"}
    fattest = labels.get(max(var, key=var.get), "one")
    cf_txt = "" if riskd.get("cornish_fisher_valid", True) else \
        " Cornish-Fisher is outside its validity domain here — defer to the historical figure."
    st.caption(f"Skew {m['skew']:.2f}, excess kurtosis {m['excess_kurtosis']:.2f}; Jarque-Bera "
               f"p={jb['p_value']:.3g} → {normal_txt} (fitted Student-t ν={dof:.1f}). The largest "
               f"1-week VaR is the **{fattest}** estimate. Note: positive skew can pull the "
               f"Cornish-Fisher left tail *below* Gaussian even when kurtosis is high, so the "
               f"methods need not be monotone; the historical and CVaR figures anchor the realized "
               f"tail.{cf_txt}")

    st.subheader("Per-holding scenario impact")
    pas, pnl = result["per_asset_scenario_return"], result["per_asset_pnl_contribution"]
    st.dataframe(pd.DataFrame({
        "Ticker": tickers, "Name": [asset_names[t] for t in tickers],
        "Weight": [f"{weights[t]*100:.1f}%" for t in tickers],
        "Scenario return": [f"{pas[t]*100:.1f}%" for t in tickers],
        "P&L contribution": [f"{pnl[t]*100:.2f}%" for t in tickers],
        "Risk % (crisis)": [f"{rc['stressed_percentage'][t]*100:.1f}%" for t in tickers],
    }), use_container_width=True, hide_index=True)

    reb = result["rebalance"]
    st.subheader("🔧 Recommended mitigation (constrained optimization)")
    if reb["applied"]:
        r1, r2, r3 = st.columns(3)
        r1.metric("Crisis volatility", pct(reb["new_volatility"]), f"{reb['volatility_change']*100:+.2f}%")
        r2.metric("Scenario drawdown", pct(reb["new_drawdown"]), f"{reb['drawdown_improvement']*100:+.2f}%")
        r3.metric("Turnover", pct(reb.get("turnover", 0.0)))
        st.caption(reb.get("method", "constrained optimization"))
        wd = pd.DataFrame({
            "Ticker": tickers,
            "Current": [f"{reb['old_weights'][t]*100:.1f}%" for t in tickers],
            "Optimized": [f"{reb['new_weights'][t]*100:.1f}%" for t in tickers],
        })
        st.dataframe(wd, use_container_width=True, hide_index=True)
    else:
        st.write("The constrained optimizer finds no turnover-limited trade that reduces crisis "
                 "risk without worsening the scenario — the allocation is already efficient here.")

# ================================================================ REVERSE STRESS
with tab_reverse:
    st.subheader("🔄 Reverse stress testing (crisis-regime plausibility)")
    st.caption("What would make me lose X? We solve for the most *plausible* factor shock "
               "(bounded, measured against the **crisis-regime** covariance) and rank the top "
               "single-factor paths.")
    target_pct = st.slider("Target portfolio loss (%)", 5, 50, 20, 1, format="%d%%")
    target = target_pct / 100.0
    try:
        rev = api_post("/api/portfolio/reverse-stress-test",
                       {"weights": weights, "target_loss": target})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()

    if not rev.get("reachable", True):
        st.warning(rev.get("plausibility_note", "Target loss is not reachable within plausible bounds."))
    st.info(rev["commentary"])
    cc1, cc2 = st.columns([2, 1])
    with cc1:
        shocks = rev["shocks"]
        label = "worst plausible shock (target unreachable)" if not rev.get("reachable", True) \
            else "most plausible joint shock" if rev["mahalanobis_distance"] <= 3.0 \
            else "least-implausible joint shock"
        sdf = pd.DataFrame({
            "Factor": list(shocks.keys()),
            "Implied shock": [f"{v*1e4:+.0f}bps" if k in ("Rates", "Credit") else f"{v*100:+.1f}%"
                              for k, v in shocks.items()],
        })
        st.markdown(f"**{label.capitalize()}** (bounded, crisis-regime)")
        st.dataframe(sdf, use_container_width=True, hide_index=True)
    with cc2:
        st.metric("Plausibility", f"{rev['mahalanobis_distance']:.1f}σ",
                  help="Crisis-regime Mahalanobis distance; >3σ is implausible, >5σ effectively impossible.")
        st.metric("Worst plausible loss", pct(rev.get("max_loss_within_bounds", float("nan"))),
                  help="Largest loss achievable with factor moves inside plausible bounds.")

    st.markdown("**Top single-factor paths to the same loss** (feasible first; infeasible flagged)")
    adf = pd.DataFrame([{
        "Dominant factor": a["dominant_factor"],
        "Shock": (f"{a['shock_value']*1e4:+.0f}bps" if a["dominant_factor"] in ("Rates", "Credit")
                  else f"{a['shock_value']*100:+.0f}%"),
        "Feasible?": "yes" if a.get("feasible_within_bounds") else "NO (exceeds bounds)",
        "Plausibility (σ)": f"{a['mahalanobis_distance']:.1f}",
    } for a in rev["alternatives"]])
    st.dataframe(adf, use_container_width=True, hide_index=True)
    st.caption("A single-factor path marked infeasible (e.g. a >100% index move) is a "
               "mathematical artifact of forcing the whole loss through one factor — shown for "
               "intuition, never as a plausible scenario.")

# ================================================================ BACKTEST
with tab_backtest:
    st.subheader("📊 Backtest: out-of-sample skill vs. naive benchmarks")
    try:
        bt = api_get("/api/backtest")
    except Exception as exc:
        st.error(str(exc)); st.stop()

    oos = bt["out_of_sample"]
    st.caption(oos["note"])
    b1, b2, b3 = st.columns(3)
    b1.metric("OOS model RMSE (per asset)", pct(oos["overall_rmse_model"]))
    b2.metric("Skill vs. predict-zero", f"{oos['overall_skill_vs_zero']*100:+.0f}%",
              help="1 − model_RMSE / benchmark_RMSE. Positive = beats the benchmark.")
    b3.metric("Skill vs. repeat-last-crisis", f"{oos['overall_skill_vs_repeat']*100:+.0f}%")

    for sid, r in oos["scenarios"].items():
        st.markdown(f"**Predict {r['scenario_name']}** (trained on {', '.join(r['trained_on'])}) — "
                    f"skill vs zero {r['skill_vs_zero']*100:+.0f}%, vs repeat {r['skill_vs_repeat']*100:+.0f}%")
        pa = pd.DataFrame(r["per_asset"])
        if not pa.empty:
            disp = pd.DataFrame({
                "Ticker": pa["ticker"],
                "Model": (pa["model"] * 100).map("{:.1f}%".format),
                "Repeat-last": (pa["repeat_last"] * 100).map("{:.1f}%".format),
                "Realized": (pa["realized"] * 100).map("{:.1f}%".format),
                "Model error": (pa["error"] * 100).map("{:+.1f}%".format),
            })
            fig = go.Figure()
            fig.add_bar(name="Model", x=pa["ticker"], y=pa["model"] * 100)
            fig.add_bar(name="Realized", x=pa["ticker"], y=pa["realized"] * 100)
            cA, cB = st.columns([1, 1])
            cA.dataframe(disp, use_container_width=True, hide_index=True)
            fig.update_layout(barmode="group", height=300, yaxis_title="Crisis-window return %")
            cB.plotly_chart(fig, use_container_width=True)

    with st.expander("In-sample calibration check (not a skill test)"):
        st.caption(bt["in_sample"]["note"])
        for sid, r in bt["in_sample"]["scenarios"].items():
            st.write(f"**{r['scenario_name']}** — MAE {pct(r['mae'])}, RMSE {pct(r['rmse'])}")

# ================================================================ MODEL & DIAGNOSTICS
with tab_model:
    st.subheader("Factor exposures (the model's assumptions)")
    st.dataframe(pd.DataFrame(assets), use_container_width=True, hide_index=True)

    st.subheader("Portfolio factor regression (OLS with t-stats & multicollinearity diagnostics)")
    try:
        reg = api_post("/api/portfolio/factor-regression", {"weights": weights})
        rows = [{"Factor": f, "Beta": f"{reg['betas'][f]:.3f}",
                 "t-stat": f"{reg['t_stats'][f]:.2f}",
                 "Std err": f"{reg['std_errors'][f]:.3f}",
                 "VIF": f"{reg['vif'][f]:.1f}"} for f in reg["betas"]]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"R² = {reg['r_squared']:.3f} (adj {reg['adj_r_squared']:.3f}). "
                   f"Condition number = {reg['condition_number']:.1f}. VIF > ~5-10 flags "
                   f"multicollinearity — disclosed, not hidden. Note: this R² is elevated "
                   f"because the shipped data is factor-generated synthetic (see Limitations); "
                   f"on real market data a 6-factor weekly model typically explains ~60-85%, "
                   f"and the provider interface makes that swap one line of code.")
    except RuntimeError as exc:
        st.error(str(exc))

    st.subheader("Risk contribution with bootstrap confidence intervals")
    try:
        rr = api_post("/api/portfolio/risk-contribution", {"weights": weights})
        ci = rr["pctr_confidence_interval"]
        cidf = pd.DataFrame({
            "Ticker": tickers,
            "Capital %": [f"{weights[t]*100:.1f}%" for t in tickers],
            "Risk % (point)": [f"{ci[t]['point']*100:.1f}%" for t in tickers],
            f"{int(rr['pctr_ci_confidence']*100)}% CI": [
                f"[{ci[t]['lower']*100:.1f}%, {ci[t]['upper']*100:.1f}%]" for t in tickers],
        })
        st.dataframe(cidf, use_container_width=True, hide_index=True)
        st.caption("Block-bootstrap intervals: MCTR is a noisy estimate, so point values are "
                   "shown with uncertainty rather than as false precision.")
        if rr.get("crisis_cov_used_fallback"):
            st.warning("Too few crisis weeks to estimate a distinct crisis covariance — "
                       "crisis attribution fell back to the full-sample estimate.")
    except RuntimeError as exc:
        st.error(str(exc))

    st.subheader("Regime detection")
    st.write(f"Detected **{rg['n_crisis_weeks']} crisis weeks** of {rg['n_weeks']} "
             f"({rg['crisis_fraction']*100:.1f}%) via a {rg['detection']}. Under pure normality "
             f"only ~{rg['expected_fraction_if_normal']*100:.0f}% would be flagged, so this "
             f"reflects a genuine regime, not a fixed quantile. Crisis-week volatility is "
             f"**{rg['vol_amplification']:.1f}×** the calm level.")

st.divider()
st.caption("Educational demonstration — not investment advice. See docs/METHODOLOGY.md for all "
           "formulas, calibration sources, and limitations.")
