"""MacroShock dashboard (Streamlit).

A portfolio consulting co-pilot UI:
  * weight sliders + scenario selector
  * before/after drawdown and factor P&L attribution
  * risk-vs-capital (MCTR) decomposition chart  -- the "40% of capital, 70% of risk" insight
  * reverse stress testing (target loss -> most plausible shock)
  * auto-generated investment commentary

Talks to the Flask API; falls back to a clear message if the API is unreachable.
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


# --------------------------------------------------------------------- API helpers
@st.cache_data(ttl=60)
def api_get(path: str) -> dict:
    r = requests.get(f"{API_BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: dict) -> dict:
    r = requests.post(f"{API_BASE}{path}", json=payload, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("error", r.text))
    return r.json()


def money(x: float) -> str:
    return f"{x * 100:.2f}%"


# --------------------------------------------------------------------- load reference
try:
    assets = api_get("/api/assets")["assets"]
    scenarios = api_get("/api/scenarios")["scenarios"]
except Exception as exc:  # API not up yet
    st.error(f"Cannot reach the MacroShock API at {API_BASE}. Is the backend running? ({exc})")
    st.stop()

tickers = [a["ticker"] for a in assets]
asset_names = {a["ticker"]: a["name"] for a in assets}

st.title("⚡ MacroShock")
st.caption(
    "A portfolio consulting co-pilot — what breaks, why it breaks, which holding is to "
    "blame, and the single trade that reduces the pain."
)

# --------------------------------------------------------------------- sidebar controls
st.sidebar.header("Portfolio")
default_weights = {"SPY": 40, "IEF": 20, "LQD": 20, "GLD": 10, "DBC": 10}
raw = {}
for t in tickers:
    raw[t] = st.sidebar.slider(f"{t} — {asset_names[t]}", 0, 100, default_weights.get(t, 0), 1)

total = sum(raw.values())
if total == 0:
    st.sidebar.error("Allocate some weight to at least one asset.")
    st.stop()
weights = {t: v / total for t, v in raw.items()}
st.sidebar.metric("Total allocation", f"{total}%", help="Weights are normalized to 100%.")

st.sidebar.header("Scenario")
scenario_labels = {s["scenario_id"]: s["name"] for s in scenarios}
scenario_id = st.sidebar.selectbox(
    "Stress scenario", options=list(scenario_labels.keys()),
    format_func=lambda k: scenario_labels[k],
)
confidence = st.sidebar.select_slider("VaR confidence", options=[0.90, 0.95, 0.975, 0.99], value=0.95)

# --------------------------------------------------------------------- run stress test
try:
    result = api_post("/api/portfolio/stress-test",
                      {"weights": weights, "scenario_id": scenario_id, "confidence": confidence})
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

scenario = result["scenario"]

# --- headline metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("Scenario drawdown", money(result["portfolio_drawdown"]))
c2.metric(f"VaR ({confidence:.0%})", money(result["var"]), help="Parametric 1-week VaR.")
c3.metric(f"CVaR ({confidence:.0%})", money(result["cvar"]), help="Expected shortfall beyond VaR.")
c4.metric("Annualized vol", money(result["volatility_annual"]))

cache_tag = "cache hit ⚡" if result.get("cache_hit") else "computed"
st.caption(f"Scenario: **{scenario['name']}** — {scenario['description']}  ·  "
           f"{cache_tag} in {result.get('latency_ms', 0)} ms")

# --------------------------------------------------------------------- commentary
st.subheader("🧭 Investment commentary")
st.info(result["commentary"])

# --------------------------------------------------------------------- attribution row
left, right = st.columns(2)

with left:
    st.subheader("Factor P&L attribution")
    fp = result["factor_pnl_attribution"]
    fdf = pd.DataFrame({"Factor": list(fp.keys()), "P&L": [v * 100 for v in fp.values()]})
    fig = px.bar(fdf, x="Factor", y="P&L", color="P&L", color_continuous_scale="RdYlGn",
                 title="Where the loss comes from (%)")
    fig.update_layout(showlegend=False, coloraxis_showscale=False, height=360)
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Risk vs. capital (MCTR)")
    rc = result["risk_contribution"]["percentage"]
    cap = result["weights"]
    comp = pd.DataFrame({
        "Ticker": tickers,
        "Capital weight": [cap[t] * 100 for t in tickers],
        "Risk contribution": [rc[t] * 100 for t in tickers],
    })
    fig2 = go.Figure()
    fig2.add_bar(name="Capital weight %", x=comp["Ticker"], y=comp["Capital weight"])
    fig2.add_bar(name="Risk contribution %", x=comp["Ticker"], y=comp["Risk contribution"])
    fig2.update_layout(barmode="group", height=360,
                       title="Capital weight vs. share of total risk")
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("When an asset's risk bar towers over its capital bar, it dominates portfolio "
               "risk far more than its allocation suggests.")

# --------------------------------------------------------------------- per-asset table
st.subheader("Per-holding scenario impact")
pas = result["per_asset_scenario_return"]
pnl = result["per_asset_pnl_contribution"]
table = pd.DataFrame({
    "Ticker": tickers,
    "Name": [asset_names[t] for t in tickers],
    "Weight": [f"{result['weights'][t]*100:.1f}%" for t in tickers],
    "Scenario return": [f"{pas[t]*100:.1f}%" for t in tickers],
    "P&L contribution": [f"{pnl[t]*100:.2f}%" for t in tickers],
    "Risk share": [f"{rc[t]*100:.1f}%" for t in tickers],
})
st.dataframe(table, use_container_width=True, hide_index=True)

# --------------------------------------------------------------------- rebalance
reb = result["rebalance"]
st.subheader("🔧 Recommended mitigation")
if reb["applied"]:
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Trade", f"{reb['from_ticker']} → {reb['to_ticker']}", f"{reb['shift']*100:.0f}%")
    rc2.metric("Drawdown", money(reb["new_drawdown"]),
               f"{reb['drawdown_improvement']*100:+.2f}% improvement")
    rc3.metric("Volatility", money(reb["new_volatility"]),
               f"{reb['volatility_change']*100:+.2f}%")
    st.write(reb["reason"])
else:
    st.write(reb["reason"])

# --------------------------------------------------------------------- reverse stress
st.divider()
st.subheader("🔄 Reverse stress testing")
st.caption("Instead of 'what happens in 2008?', ask: **what scenario would make me lose X?** "
           "MacroShock solves for the single most *plausible* combination of factor shocks.")
target = st.slider("Target portfolio loss", 0.05, 0.50, 0.20, 0.01, format="%.0f%%")
try:
    rev = api_post("/api/portfolio/reverse-stress-test",
                   {"weights": weights, "target_loss": target})
    st.info(rev["commentary"])
    shocks = rev["shocks"]
    sdf = pd.DataFrame({
        "Factor": list(shocks.keys()),
        "Implied shock": [
            f"{v*1e4:+.0f}bps" if k in ("Rates", "Credit") else f"{v*100:+.1f}%"
            for k, v in shocks.items()
        ],
    })
    rc1, rc2 = st.columns([2, 1])
    rc1.dataframe(sdf, use_container_width=True, hide_index=True)
    rc2.metric("Plausibility (Mahalanobis)", f"{rev['mahalanobis_distance']:.2f}σ",
               help="Lower = more plausible and more concerning.")
except RuntimeError as exc:
    st.error(str(exc))

st.divider()
st.caption("Educational demonstration — not investment advice. See docs/METHODOLOGY.md for "
           "all formulas and calibration sources.")
