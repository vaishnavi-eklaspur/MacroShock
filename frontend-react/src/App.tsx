import { useEffect, useMemo, useState } from "react";
import { api, type Asset, type Scenario, type StressResult } from "./api";

const pct = (x: number) => `${(x * 100).toFixed(2)}%`;

export function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [scenarioId, setScenarioId] = useState<string>("");
  const [result, setResult] = useState<StressResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.assets(), api.scenarios()])
      .then(([a, s]) => {
        setAssets(a.assets);
        setScenarios(s.scenarios);
        setScenarioId(s.scenarios[0]?.scenario_id ?? "");
        // sensible default weights
        const w: Record<string, number> = {};
        a.assets.forEach((x, i) => (w[x.ticker] = i < 4 ? 25 : 0));
        setWeights(w);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const total = useMemo(() => Object.values(weights).reduce((s, v) => s + v, 0), [weights]);

  async function runStress() {
    if (total <= 0) return;
    setLoading(true);
    setError(null);
    try {
      const norm: Record<string, number> = {};
      Object.entries(weights).forEach(([t, v]) => (norm[t] = v / total));
      setResult(await api.stressTest(norm, scenarioId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const factorRows = result
    ? Object.entries(result.factor_pnl_attribution).sort((a, b) => a[1] - b[1])
    : [];
  const maxAbs = Math.max(1e-9, ...factorRows.map(([, v]) => Math.abs(v)));

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>⚡ MacroShock <span style={{ fontWeight: 400, fontSize: 16, color: "#888" }}>· React + TypeScript client</span></h1>
      {error && <p style={{ color: "crimson" }}>Error: {error}</p>}

      <section style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 280px" }}>
          <h3>Portfolio weights (%)</h3>
          {assets.map((a) => (
            <label key={a.ticker} style={{ display: "block", margin: "4px 0", fontSize: 14 }}>
              {a.ticker} — {a.name}
              <input
                type="range" min={0} max={100} value={weights[a.ticker] ?? 0}
                onChange={(e) => setWeights({ ...weights, [a.ticker]: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
              <span>{weights[a.ticker] ?? 0}%</span>
            </label>
          ))}
          <p style={{ fontSize: 13, color: "#888" }}>Total {total}% (normalized to 100%).</p>
        </div>

        <div style={{ flex: "1 1 280px" }}>
          <h3>Scenario</h3>
          <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} style={{ width: "100%", padding: 6 }}>
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>{s.name}</option>
            ))}
          </select>
          <button onClick={runStress} disabled={loading || total <= 0} style={{ marginTop: 12, padding: "8px 16px" }}>
            {loading ? "Running…" : "Run stress test"}
          </button>

          {result && (
            <div style={{ marginTop: 16 }}>
              <h2 style={{ margin: "8px 0" }}>Drawdown: {pct(result.portfolio_drawdown)}</h2>
              <p style={{ fontSize: 13 }}>
                Hist VaR {pct(result.risk.var.historical)} · Ann vol {pct(result.risk.volatility_annual)}
              </p>
            </div>
          )}
        </div>
      </section>

      {result && (
        <section style={{ marginTop: 24 }}>
          <h3>Factor P&amp;L attribution</h3>
          {factorRows.map(([f, v]) => (
            <div key={f} style={{ display: "flex", alignItems: "center", gap: 8, margin: "3px 0" }}>
              <span style={{ width: 90, fontSize: 13 }}>{f}</span>
              <div style={{ flex: 1, background: "#eee", height: 18, position: "relative" }}>
                <div style={{
                  position: "absolute", left: v < 0 ? "auto" : "50%", right: v < 0 ? "50%" : "auto",
                  width: `${(Math.abs(v) / maxAbs) * 50}%`, height: "100%",
                  background: v < 0 ? "#d9534f" : "#5cb85c",
                }} />
              </div>
              <span style={{ width: 70, fontSize: 13, textAlign: "right" }}>{pct(v)}</span>
            </div>
          ))}
          <h3 style={{ marginTop: 16 }}>Commentary</h3>
          <p style={{ background: "#f6f8fa", padding: 12, borderRadius: 6, fontSize: 14 }}>{result.commentary}</p>
        </section>
      )}
    </main>
  );
}
