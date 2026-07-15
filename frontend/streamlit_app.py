"""MacroShock dashboard (Streamlit).

A portfolio consulting co-pilot: what breaks, why (regime-aware), which holding is to blame
(with confidence intervals), how fat the tail is (with a normality test), the optimized trade
that helps, reverse stress in the crisis regime, an out-of-sample backtest with a skill score,
a custom-scenario builder, side-by-side portfolio comparison, and a downloadable report.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:5000")
API_KEY = os.getenv("MACROSHOCK_API_KEY")
st.set_page_config(page_title="MacroShock", page_icon="⚡", layout="wide")


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


@st.cache_data(ttl=60)
def api_get(path: str) -> dict:
    r = requests.get(f"{API_BASE}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: dict) -> dict:
    r = requests.post(f"{API_BASE}{path}", json=payload, timeout=30, headers=_headers())
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("error", r.text))
    return r.json()


def api_delete(path: str) -> dict:
    r = requests.delete(f"{API_BASE}{path}", timeout=30, headers=_headers())
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
factor_names = meta["factors"]

# --- named preset portfolios (weights in %) -----------------------------------------
DEFAULTS = {"SPY": 20, "QQQ": 8, "IWM": 4, "EFA": 8, "EEM": 5, "IEF": 10, "TLT": 5,
            "TIP": 5, "LQD": 10, "HYG": 5, "GLD": 6, "DBC": 4, "VNQ": 10}
PRESETS = {
    "Diversified (default)": DEFAULTS,
    "60/40 (SPY / IEF)": {"SPY": 60, "IEF": 40},
    "All-equity (SPY)": {"SPY": 100},
    "All-weather (Dalio-style)": {"SPY": 30, "TLT": 40, "IEF": 15, "GLD": 8, "DBC": 7},
    "Barbell (stocks + long bonds)": {"SPY": 50, "TLT": 50},
}


def weights_from_pct(pctmap: dict) -> dict:
    total = sum(pctmap.get(t, 0) for t in tickers)
    return {t: pctmap.get(t, 0) / total for t in tickers} if total else {}


# Apply a pending preset/load BEFORE the sliders are built (Streamlit rule).
for t in tickers:
    st.session_state.setdefault(f"w_{t}", DEFAULTS.get(t, 0))
if "_pending_weights" in st.session_state:
    pend = st.session_state.pop("_pending_weights")
    for t in tickers:
        st.session_state[f"w_{t}"] = int(round(pend.get(t, 0)))

# ---------------------------------------------------------------- sidebar
st.sidebar.header("Portfolio")

preset_name = st.sidebar.selectbox("Preset", ["(keep current)"] + list(PRESETS))
if st.sidebar.button("Apply preset", use_container_width=True) and preset_name != "(keep current)":
    st.session_state["_pending_weights"] = PRESETS[preset_name]
    st.rerun()

with st.sidebar.expander("Adjust weights", expanded=True):
    raw = {t: st.slider(f"{t} — {asset_names[t]}", 0, 100, key=f"w_{t}") for t in tickers}

total = sum(raw.values())
if total == 0:
    st.sidebar.error("Allocate some weight to at least one asset.")
    st.stop()
weights = {t: v / total for t, v in raw.items()}
st.sidebar.metric("Total allocation", f"{total}%", help="Weights are normalized to 100%.")

# --- save / load named portfolios (persisted server-side) ---------------------------
def server_portfolios() -> dict:
    try:
        return {p["name"]: p["weights"] for p in api_get("/api/portfolios")["portfolios"]}
    except Exception:
        return {}


with st.sidebar.expander("Save / load portfolios (server)"):
    name = st.text_input("Name", placeholder="e.g. Client A")
    if st.button("Save to server", use_container_width=True) and name:
        try:
            api_post("/api/portfolios", {"name": name, "weights": weights})
            api_get.clear()
            st.success(f"Saved '{name}'.")
        except Exception as exc:
            st.error(str(exc))
    saved = server_portfolios()
    if saved:
        pick = st.selectbox("Saved portfolios", ["-"] + list(saved))
        cL, cD = st.columns(2)
        if pick != "-" and cL.button("Load", use_container_width=True):
            st.session_state["_pending_weights"] = {t: saved[pick].get(t, 0) * 100 for t in tickers}
            st.rerun()
        if pick != "-" and cD.button("Delete", use_container_width=True):
            try:
                api_delete(f"/api/portfolios/{pick}"); api_get.clear(); st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.download_button("Export all (JSON)", json.dumps(saved, indent=2),
                           "macroshock_portfolios.json", "application/json",
                           use_container_width=True)

st.sidebar.header("Scenario")
scenario_labels = {s["scenario_id"]: s["name"] for s in scenarios}
scenario_id = st.sidebar.selectbox("Stress scenario", list(scenario_labels.keys()),
                                   format_func=lambda k: scenario_labels[k])
confidence = st.sidebar.select_slider("VaR confidence", [0.90, 0.95, 0.975, 0.99], value=0.95)

st.sidebar.divider()
rg = meta["regime"]
src = meta.get("dataset", {}).get("source", "unknown")
badge = "🟢 live" if src.startswith(("yahoo", "csv")) else "🟡 synthetic"
st.sidebar.caption(f"Data: **{badge}** ({src})")
st.sidebar.caption(f"Model v{meta['model_version']} · {meta['shrinkage_target'].split('(')[0].strip()} "
                   f"shrinkage δ={meta['shrinkage_intensity']:.2f}")
st.sidebar.caption(f"Regime: {rg['n_crisis_weeks']}/{rg['n_weeks']} crisis weeks detected, "
                   f"vol {rg['vol_amplification']:.1f}× calm")

st.title("⚡ MacroShock")
st.caption("A portfolio consulting co-pilot — what breaks, why it breaks, which holding is to "
           "blame, and the single trade that reduces the pain.")


# ================================================================ shared renderer
def fmt_shock(name: str, val: float) -> str:
    return f"{val*1e4:+.0f}bps" if name in ("Rates", "Credit") else f"{val*100:+.1f}%"


def build_report_html(result: dict, weights: dict) -> str:
    scn = result["scenario"]
    fp = result["factor_pnl_attribution"]
    rows = "".join(
        f"<tr><td>{t}</td><td>{asset_names[t]}</td><td>{weights[t]*100:.1f}%</td>"
        f"<td>{result['per_asset_scenario_return'][t]*100:.1f}%</td>"
        f"<td>{result['per_asset_pnl_contribution'][t]*100:.2f}%</td></tr>"
        for t in tickers if weights[t] > 0)
    factors = "".join(f"<tr><td>{k}</td><td>{v*100:+.2f}%</td></tr>" for k, v in fp.items())
    return f"""<!doctype html><meta charset="utf-8"><title>MacroShock report</title>
<style>body{{font-family:system-ui,Arial;margin:40px;color:#1a1a1a}}
h1{{color:#b8860b}}table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:6px 10px;text-align:left}}
.big{{font-size:28px;font-weight:700}}.muted{{color:#666}}</style>
<h1>⚡ MacroShock — Stress Report</h1>
<p class="muted">Generated {dt.datetime.now():%Y-%m-%d %H:%M} · scenario: <b>{scn['name']}</b></p>
<p>{scn['description']}</p>
<p class="big">Scenario drawdown: {result['portfolio_drawdown']*100:.2f}%</p>
<h3>Investment commentary</h3><p>{result['commentary']}</p>
<h3>Factor P&amp;L attribution</h3><table><tr><th>Factor</th><th>P&amp;L</th></tr>{factors}</table>
<h3>Per-holding impact</h3>
<table><tr><th>Ticker</th><th>Name</th><th>Weight</th><th>Scenario return</th><th>P&amp;L</th></tr>
{rows}</table>
<p class="muted">Educational demonstration — not investment advice.</p>"""


def render_stress(result: dict, weights: dict, confidence: float, key_prefix: str = ""):
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
        held = [t for t in tickers if weights[t] > 0]
        fig2 = go.Figure()
        fig2.add_bar(name="Capital %", x=held, y=[weights[t] * 100 for t in held])
        fig2.add_bar(name="Risk % (calm)", x=held, y=[rc["calm_percentage"][t] * 100 for t in held])
        fig2.add_bar(name="Risk % (crisis)", x=held, y=[rc["stressed_percentage"][t] * 100 for t in held])
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
    cf_txt = "" if riskd.get("cornish_fisher_valid", True) else \
        " Cornish-Fisher is outside its validity domain here — defer to the historical figure."
    st.caption(f"Skew {m['skew']:.2f}, excess kurtosis {m['excess_kurtosis']:.2f}; Jarque-Bera "
               f"p={jb['p_value']:.3g} → {normal_txt} (fitted Student-t ν={dof:.1f}).{cf_txt}")

    st.subheader("Per-holding scenario impact")
    pas, pnl, rc = result["per_asset_scenario_return"], result["per_asset_pnl_contribution"], \
        result["risk_contribution"]
    held = [t for t in tickers if weights[t] > 0]
    holdings = pd.DataFrame({
        "Ticker": held, "Name": [asset_names[t] for t in held],
        "Weight": [f"{weights[t]*100:.1f}%" for t in held],
        "Scenario return": [f"{pas[t]*100:.1f}%" for t in held],
        "P&L contribution": [f"{pnl[t]*100:.2f}%" for t in held],
        "Risk % (crisis)": [f"{rc['stressed_percentage'][t]*100:.1f}%" for t in held],
    })
    st.dataframe(holdings, use_container_width=True, hide_index=True)

    reb = result["rebalance"]
    st.subheader("🔧 Recommended mitigation (constrained optimization)")
    if reb["applied"]:
        r1, r2, r3 = st.columns(3)
        r1.metric("Crisis volatility", pct(reb["new_volatility"]), f"{reb['volatility_change']*100:+.2f}%")
        r2.metric("Scenario drawdown", pct(reb["new_drawdown"]), f"{reb['drawdown_improvement']*100:+.2f}%")
        r3.metric("Turnover", pct(reb.get("turnover", 0.0)))
        st.caption(reb.get("method", "constrained optimization"))
        st.dataframe(pd.DataFrame({
            "Ticker": held,
            "Current": [f"{reb['old_weights'][t]*100:.1f}%" for t in held],
            "Optimized": [f"{reb['new_weights'][t]*100:.1f}%" for t in held],
        }), use_container_width=True, hide_index=True)
    else:
        st.write("The constrained optimizer finds no turnover-limited trade that reduces crisis "
                 "risk without worsening the scenario — the allocation is already efficient here.")

    st.subheader("📥 Export")
    d1, d2 = st.columns(2)
    d1.download_button("Download holdings (CSV)", holdings.to_csv(index=False),
                       "macroshock_holdings.csv", "text/csv", use_container_width=True,
                       key=f"{key_prefix}_csv")
    d2.download_button("Download report (HTML)", build_report_html(result, weights),
                       "macroshock_report.html", "text/html", use_container_width=True,
                       key=f"{key_prefix}_html",
                       help="Open in a browser and Print → Save as PDF for a shareable report.")


tab_stress, tab_custom, tab_compare, tab_bench, tab_reverse, tab_backtest, tab_model = st.tabs(
    ["Stress test", "Scenario builder", "Compare A/B", "Benchmark-relative", "Reverse stress",
     "Backtest (out-of-sample)", "Model & diagnostics"])

# ================================================================ STRESS TEST
with tab_stress:
    try:
        result = api_post("/api/portfolio/stress-test",
                          {"weights": weights, "scenario_id": scenario_id, "confidence": confidence})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()
    render_stress(result, weights, confidence, key_prefix="scn")

# ================================================================ CUSTOM SCENARIO BUILDER
with tab_custom:
    st.subheader("🎛️ Build your own scenario")
    st.caption("Set any factor shocks and price the portfolio instantly — the same attribution, "
               "tail and mitigation engine, against a shock vector you define.")
    name = st.text_input("Scenario name", "My scenario")
    cols = st.columns(3)
    ui = {
        "Equity": cols[0].slider("Equity shock (%)", -60, 60, -25, 1),
        "Commodity": cols[0].slider("Commodity shock (%)", -70, 70, 0, 1),
        "Rates": cols[1].slider("Rates Δyield (bps)", -400, 400, 50, 5),
        "Credit": cols[1].slider("Credit Δspread (bps)", -200, 800, 150, 5),
        "Liquidity": cols[2].slider("Liquidity shock (%)", -50, 20, -5, 1),
        "FX": cols[2].slider("USD (FX) shock (%)", -25, 25, 5, 1),
    }
    shocks = {"Equity": ui["Equity"] / 100, "Commodity": ui["Commodity"] / 100,
              "Rates": ui["Rates"] / 1e4, "Credit": ui["Credit"] / 1e4,
              "Liquidity": ui["Liquidity"] / 100, "FX": ui["FX"] / 100}
    shocks = {f: shocks.get(f, 0.0) for f in factor_names}
    try:
        custom = api_post("/api/portfolio/custom-stress-test",
                          {"weights": weights, "shocks": shocks, "name": name,
                           "confidence": confidence})
        render_stress(custom, weights, confidence, key_prefix="custom")
    except RuntimeError as exc:
        st.error(str(exc))

# ================================================================ COMPARE A/B
with tab_compare:
    st.subheader("⚖️ Compare two portfolios under the same shock")
    st.caption(f"Portfolio **A** = your current sidebar allocation. Pick **B** below; both are "
               f"stressed under **{scenario_labels[scenario_id]}**.")
    options = {f"Preset · {k}": v for k, v in PRESETS.items()}
    options.update({f"Saved · {k}": v for k, v in server_portfolios().items()})
    b_label = st.selectbox("Portfolio B", list(options))
    wB = weights_from_pct(options[b_label])
    try:
        rA = api_post("/api/portfolio/stress-test",
                      {"weights": weights, "scenario_id": scenario_id, "confidence": confidence})
        rB = api_post("/api/portfolio/stress-test",
                      {"weights": wB, "scenario_id": scenario_id, "confidence": confidence})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()

    def worst_factor(r):
        fp = r["factor_pnl_attribution"]
        return min(fp, key=fp.get)

    comp = pd.DataFrame({
        "Metric": ["Scenario drawdown", f"Historical VaR ({confidence:.0%})", "Annualized vol",
                   "Worst factor", "Crisis vol after fix"],
        "A (current)": [pct(rA["portfolio_drawdown"]), pct(rA["risk"]["var"]["historical"]),
                        pct(rA["risk"]["volatility_annual"]), worst_factor(rA),
                        pct(rA["rebalance"]["new_volatility"])],
        "B (" + b_label.split("· ")[-1] + ")": [
            pct(rB["portfolio_drawdown"]), pct(rB["risk"]["var"]["historical"]),
            pct(rB["risk"]["volatility_annual"]), worst_factor(rB),
            pct(rB["rebalance"]["new_volatility"])],
    })
    st.dataframe(comp, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_bar(name="A (current)", x=["Drawdown", "Hist VaR", "Ann vol"],
                y=[rA["portfolio_drawdown"] * 100, rA["risk"]["var"]["historical"] * 100,
                   rA["risk"]["volatility_annual"] * 100])
    fig.add_bar(name=f"B ({b_label.split('· ')[-1]})", x=["Drawdown", "Hist VaR", "Ann vol"],
                y=[rB["portfolio_drawdown"] * 100, rB["risk"]["var"]["historical"] * 100,
                   rB["risk"]["volatility_annual"] * 100])
    fig.update_layout(barmode="group", height=380, yaxis_title="%")
    st.plotly_chart(fig, use_container_width=True)
    dd = (rB["portfolio_drawdown"] - rA["portfolio_drawdown"]) * 100
    st.info(f"Under {scenario_labels[scenario_id]}, **B draws down {abs(dd):.1f}pp "
            f"{'less' if dd > 0 else 'more'}** than A.")

# ================================================================ BENCHMARK-RELATIVE
with tab_bench:
    st.subheader("🎯 Benchmark-relative analytics (active risk)")
    st.caption("How IPS actually works: a model portfolio is measured **against a strategic "
               "benchmark** — tracking error, active-risk contribution, and factor tilts, not "
               "just absolute risk.")
    try:
        benches = api_get("/api/benchmarks")["benchmarks"]
    except Exception as exc:
        st.error(str(exc)); st.stop()
    bname = st.selectbox("Strategic benchmark", list(benches))
    try:
        ar = api_post("/api/portfolio/active-risk", {"weights": weights, "benchmark_id": bname})
    except RuntimeError as exc:
        st.error(str(exc)); st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tracking error (calm, ann.)", pct(ar["tracking_error_annual_calm"]))
    m2.metric("Tracking error (crisis, ann.)", pct(ar["tracking_error_annual_crisis"]),
              help="Active risk rises in the crisis regime as correlations tighten.")
    m3.metric("Active share", pct(ar["active_share"]))
    m4.metric("Port vol vs bench", pct(ar["portfolio_vol_annual"]),
              f"{(ar['portfolio_vol_annual']-ar['benchmark_vol_annual'])*100:+.2f}pp")

    held = [t for t in tickers if abs(ar["active_weights"][t]) > 1e-9]
    left, right = st.columns(2)
    with left:
        st.markdown("**Active factor tilts** (portfolio − benchmark exposure)")
        tl = ar["factor_tilts"]
        tdf = pd.DataFrame({"Factor": list(tl.keys()), "Active exposure": list(tl.values())})
        figt = px.bar(tdf, x="Factor", y="Active exposure", color="Active exposure",
                      color_continuous_scale="RdBu")
        figt.update_layout(showlegend=False, coloraxis_showscale=False, height=340)
        st.plotly_chart(figt, use_container_width=True)
    with right:
        st.markdown("**Active weights vs benchmark**")
        aw = pd.DataFrame({
            "Ticker": held,
            "Portfolio": [f"{weights[t]*100:.1f}%" for t in held],
            "Benchmark": [f"{ar['benchmark_weights'][t]*100:.1f}%" for t in held],
            "Active": [f"{ar['active_weights'][t]*100:+.1f}%" for t in held],
            "Active risk % (crisis)": [f"{ar['active_risk_pctr_crisis'][t]*100:+.1f}%" for t in held],
        })
        st.dataframe(aw, use_container_width=True, hide_index=True)
    st.caption("Active-risk contribution decomposes tracking error across holdings (Euler "
               "identity, sums to 100%). Factor tilts show where the portfolio is over/under the "
               "benchmark in macro-factor space — the language of multi-asset portfolio construction.")

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
            "Implied shock": [fmt_shock(k, v) for k, v in shocks.items()],
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
        "Shock": fmt_shock(a["dominant_factor"], a["shock_value"]),
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

    # Overview: skill per crisis (all folds at a glance).
    folds = {r["scenario_name"]: r for r in oos["scenarios"].values()}
    if folds:
        ov = pd.DataFrame([{"Crisis": n, "vs predict-zero": r["skill_vs_zero"] * 100,
                            "vs repeat-last": r["skill_vs_repeat"] * 100}
                           for n, r in folds.items()])
        figov = go.Figure()
        figov.add_bar(name="Skill vs predict-zero", x=ov["Crisis"], y=ov["vs predict-zero"])
        figov.add_bar(name="Skill vs repeat-last", x=ov["Crisis"], y=ov["vs repeat-last"])
        figov.update_layout(barmode="group", height=340, yaxis_title="Skill % (higher = better)")
        st.plotly_chart(figov, use_container_width=True)

        # Interactive: pick a crisis fold to drill into.
        choice = st.selectbox("🔎 Inspect a crisis fold", list(folds))
        r = folds[choice]
        st.markdown(f"**Predicting {choice}** — trained on {', '.join(r['trained_on'])}. "
                    f"Skill vs zero **{r['skill_vs_zero']*100:+.0f}%**, vs repeat "
                    f"**{r['skill_vs_repeat']*100:+.0f}%**. The held-out crisis's realized returns "
                    f"never touch the prediction — a genuine out-of-sample test.")
        pa = pd.DataFrame(r["per_asset"])
        if not pa.empty:
            disp = pd.DataFrame({
                "Ticker": pa["ticker"],
                "Model": (pa["model"] * 100).map("{:.1f}%".format),
                "Repeat-last": (pa["repeat_last"] * 100).map("{:.1f}%".format),
                "Realized": (pa["realized"] * 100).map("{:.1f}%".format),
                "Model error": (pa["error"] * 100).map("{:+.1f}%".format),
            })
            st.dataframe(disp, use_container_width=True, hide_index=True)
            fig = go.Figure()
            fig.add_bar(name="Model prediction", x=pa["ticker"], y=pa["model"] * 100)
            fig.add_bar(name="Realized", x=pa["ticker"], y=pa["realized"] * 100)
            fig.update_layout(barmode="group", height=400, yaxis_title="Crisis-window return %")
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("In-sample calibration check (not a skill test)"):
        st.caption(bt["in_sample"]["note"])
        for sid, r in bt["in_sample"]["scenarios"].items():
            st.write(f"**{r['scenario_name']}** — MAE {pct(r['mae'])}, RMSE {pct(r['rmse'])}")

# ================================================================ MODEL & DIAGNOSTICS
with tab_model:
    st.subheader("Factor exposures (the model's assumptions)")
    st.dataframe(pd.DataFrame(assets), use_container_width=True, hide_index=True)

    st.subheader("Structural vs. estimated betas (are the factors real?)")
    try:
        exp = api_get("/api/exposures")
        erows = [{"Ticker": a["ticker"],
                  **{f"{f} (struct→est)": f"{a['structural'][f]:+.2f}→{a['estimated'][f]:+.2f}"
                     for f in ["Equity", "Rates", "Credit"]},
                  "R²": f"{a['r_squared']:.2f}"} for a in exp["assets"]]
        st.dataframe(pd.DataFrame(erows), use_container_width=True, hide_index=True)
        st.caption(f"Mean R² = **{exp['r2_mean']:.2f}** — deliberately **below 1.0**. The factors "
                   f"are independent series and betas are OLS-estimated from history, so a real "
                   f"amount of return is idiosyncratic. If factors were derived from the assets "
                   f"themselves, R² would be ~1.0 and the 'factor model' would be circular. "
                   f"Scenario pricing uses the interpretable structural betas; the backtest uses "
                   f"the estimated ones (fit on weekly data, so no leakage into the crisis test).")
    except Exception as exc:
        st.error(str(exc))

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
                   f"multicollinearity — disclosed, not hidden.")
    except RuntimeError as exc:
        st.error(str(exc))

    st.subheader("Risk contribution with bootstrap confidence intervals")
    try:
        rr = api_post("/api/portfolio/risk-contribution", {"weights": weights})
        ci = rr["pctr_confidence_interval"]
        held = [t for t in tickers if weights[t] > 0]
        cidf = pd.DataFrame({
            "Ticker": held,
            "Capital %": [f"{weights[t]*100:.1f}%" for t in held],
            "Risk % (point)": [f"{ci[t]['point']*100:.1f}%" for t in held],
            f"{int(rr['pctr_ci_confidence']*100)}% CI": [
                f"[{ci[t]['lower']*100:.1f}%, {ci[t]['upper']*100:.1f}%]" for t in held],
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
