"""MacroShock dashboard (Streamlit).

A portfolio consulting co-pilot: what breaks, why, which holding is to blame (regime-aware),
how fat the tail is, the single trade that helps - plus reverse stress testing and a
backtest of the engine against realized 2008/2020 returns.
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
    r = requests.get(f"{API_BASE}{path}", timeout=15)
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: dict) -> dict:
    r = requests.post(f"{API_BASE}{path}", json=payload, timeout=20)
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
st.sidebar.caption(f"Model v{meta['model_version']} · shrinkage "
                   f"{meta['shrinkage_intensity']:.2f} · crisis-regime vol "
                   f"{meta['regime']['vol_amplification']:.1f}x calm")

tab_stress, tab_reverse, tab_backtest, tab_model = st.tabs(
    ["Stress test", "Reverse stress", "Backtest (vs realized)", "Model & factors"])

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
              help="Instantaneous peak-to-trough shock (not annualized).")
    c2.metric(f"Historical VaR ({confidence:.0%}, 1wk)", pct(riskd["var"]["historical"]))
    c3.metric(f"Gaussian VaR ({confidence:.0%}, 1wk)", pct(riskd["var"]["gaussian"]))
    c4.metric("Annualized vol", pct(riskd["volatility_annual"]))
    tag = "cache hit ⚡" if result.get("cache_hit") else "computed"
    st.caption(f"**{scenario['name']}** — {scenario['description']}  ·  {tag} in "
               f"{result.get('latency_ms', 0)} ms")

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
        st.caption("Risk share shifts from calm to crisis because correlations tighten in stress "
                   "— the effect a single-regime model misses.")

    st.subheader("Tail check: VaR under different distributional assumptions")
    var = riskd["var"]
    vardf = pd.DataFrame({
        "Method": ["Gaussian", "Student-t (ν=5)", "Cornish-Fisher", "Historical"],
        f"1-week VaR ({confidence:.0%})": [var["gaussian"] * 100, var["student_t"] * 100,
                                            var["cornish_fisher"] * 100, var["historical"] * 100],
    })
    figv = px.bar(vardf, x="Method", y=f"1-week VaR ({confidence:.0%})", color="Method")
    figv.update_layout(showlegend=False, height=320)
    st.plotly_chart(figv, use_container_width=True)
    m = riskd["moments"]
    st.caption(f"Return skew {m['skew']:.2f}, excess kurtosis {m['excess_kurtosis']:.2f}. "
               f"When kurtosis > 0, Gaussian VaR understates the tail — hence the fatter "
               f"historical / Cornish-Fisher figures.")

    st.subheader("Per-holding scenario impact")
    pas, pnl = result["per_asset_scenario_return"], result["per_asset_pnl_contribution"]
    st.dataframe(pd.DataFrame({
        "Ticker": tickers, "Name": [asset_names[t] for t in tickers],
        "Weight": [f"{weights[t]*100:.1f}%" for t in tickers],
        "Scenario return": [f"{pas[t]*100:.1f}%" for t in tickers],
        "P&L contribution": [f"{pnl[t]*100:.2f}%" for t in tickers],
        "Risk % (crisis)": [f"{result['risk_contribution']['stressed_percentage'][t]*100:.1f}%"
                             for t in tickers],
    }), use_container_width=True, hide_index=True)

    reb = result["rebalance"]
    st.subheader("🔧 Recommended mitigation")
    if reb["applied"]:
        r1, r2, r3 = st.columns(3)
        r1.metric("Trade", f"{reb['from_ticker']} → {reb['to_ticker']}", f"{reb['shift']*100:.0f}%")
        r2.metric("Drawdown", pct(reb["new_drawdown"]),
                  f"{reb['drawdown_improvement']*100:+.2f}%")
        r3.metric("Crisis volatility", pct(reb["new_volatility"]),
                  f"{reb['volatility_change']*100:+.2f}%")
    st.write(reb["reason"])

# ================================================================ REVERSE STRESS
with tab_reverse:
    st.subheader("🔄 Reverse stress testing")
    st.caption("Instead of 'what happens in 2008?', ask: **what would make me lose X?** "
               "We solve for the most *plausible* factor shock (within economic bounds) and "
               "also show the top single-factor paths.")
    target = st.slider("Target portfolio loss", 0.05, 0.50, 0.20, 0.01, format="%.0f%%")
    try:
        rev = api_post("/api/portfolio/reverse-stress-test",
                       {"weights": weights, "target_loss": target})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()

    st.info(rev["commentary"])
    cc1, cc2 = st.columns([2, 1])
    with cc1:
        shocks = rev["shocks"]
        sdf = pd.DataFrame({
            "Factor": list(shocks.keys()),
            "Implied shock": [f"{v*1e4:+.0f}bps" if k in ("Rates", "Credit") else f"{v*100:+.1f}%"
                              for k, v in shocks.items()],
        })
        st.markdown("**Most plausible joint shock** (bounded)")
        st.dataframe(sdf, use_container_width=True, hide_index=True)
    with cc2:
        st.metric("Plausibility", f"{rev['mahalanobis_distance']:.2f}σ",
                  help="Mahalanobis distance; lower = more plausible & more concerning.")
        st.metric("Bounded solve", "yes" if rev["constrained"] else "fell back")

    st.markdown("**Top single-factor paths to the same loss** (ranked by plausibility)")
    alts = rev["alternatives"]
    adf = pd.DataFrame([{
        "Dominant factor": a["dominant_factor"],
        "Shock": next((f"{v*1e4:+.0f}bps" if k in ("Rates", "Credit") else f"{v*100:+.1f}%")
                      for k, v in a["shocks"].items() if abs(v) > 1e-9),
        "Plausibility (σ)": f"{a['mahalanobis_distance']:.2f}",
    } for a in alts])
    st.dataframe(adf, use_container_width=True, hide_index=True)

# ================================================================ BACKTEST
with tab_backtest:
    st.subheader("📊 Backtest: model prediction vs. realized crisis returns")
    st.caption("Predicted = the factor-shock model. Realized = documented 2008/2020 returns, "
               "independent of the model. This is a genuine out-of-sample check.")
    try:
        bt = api_get("/api/backtest")
    except Exception as exc:
        st.error(str(exc)); st.stop()

    b1, b2 = st.columns(2)
    b1.metric("Overall MAE (per asset)", pct(bt["overall_mae"]))
    b2.metric("Overall RMSE (per asset)", pct(bt["overall_rmse"]))

    for scenario_id_bt, r in bt["scenarios"].items():
        st.markdown(f"**{r['scenario_name']}** — MAE {pct(r['mae'])}, RMSE {pct(r['rmse'])}")
        pa = pd.DataFrame(r["per_asset"])
        if not pa.empty:
            pa_disp = pd.DataFrame({
                "Ticker": pa["ticker"],
                "Predicted": (pa["predicted"] * 100).map("{:.1f}%".format),
                "Realized": (pa["realized"] * 100).map("{:.1f}%".format),
                "Error": (pa["error"] * 100).map("{:+.1f}%".format),
            })
            fig = go.Figure()
            fig.add_bar(name="Predicted", x=pa["ticker"], y=pa["predicted"] * 100)
            fig.add_bar(name="Realized", x=pa["ticker"], y=pa["realized"] * 100)
            fig.update_layout(barmode="group", height=300,
                              yaxis_title="Crisis-window return %")
            cA, cB = st.columns([1, 1])
            cA.dataframe(pa_disp, use_container_width=True, hide_index=True)
            cB.plotly_chart(fig, use_container_width=True)

# ================================================================ MODEL
with tab_model:
    st.subheader("Factor exposures (the model's assumptions)")
    st.dataframe(pd.DataFrame(assets), use_container_width=True, hide_index=True)

    st.subheader("Portfolio factor regression (OLS with t-stats)")
    try:
        reg = api_post("/api/portfolio/factor-regression", {"weights": weights})
        rows = [{"Factor": f, "Beta": f"{reg['betas'][f]:.3f}",
                 "t-stat": f"{reg['t_stats'][f]:.2f}",
                 "Std err": f"{reg['std_errors'][f]:.3f}"} for f in reg["betas"]]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"R² = {reg['r_squared']:.3f} (adjusted {reg['adj_r_squared']:.3f}). "
                   f"A realistic factor model explains well below 100% of variance — a near-1.0 "
                   f"R² would signal circular/planted data.")
    except RuntimeError as exc:
        st.error(str(exc))

    rg = meta["regime"]
    st.subheader("Regime statistics")
    st.write(f"Detected **{rg['n_crisis_weeks']} crisis weeks** out of {rg['n_weeks']} "
             f"({rg['crisis_fraction']*100:.0f}%); average volatility is "
             f"**{rg['vol_amplification']:.1f}×** higher in the crisis regime than in calm periods.")

st.divider()
st.caption("Educational demonstration — not investment advice. See docs/METHODOLOGY.md for all "
           "formulas, calibration sources, and limitations.")
