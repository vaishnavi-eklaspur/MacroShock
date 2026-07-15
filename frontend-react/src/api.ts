// Typed client for the MacroShock Flask API. Types mirror the JSON contract so the UI is
// compile-time-checked against the backend.

export interface Asset {
  ticker: string;
  name: string;
  asset_class: string;
}

export interface Scenario {
  scenario_id: string;
  name: string;
  description: string;
  is_historical: boolean;
}

export interface StressResult {
  scenario: { scenario_id: string; name: string; description: string };
  portfolio_drawdown: number;
  factor_pnl_attribution: Record<string, number>;
  per_asset_pnl_contribution: Record<string, number>;
  commentary: string;
  risk: {
    volatility_annual: number;
    var: { gaussian: number; historical: number; student_t: number; cornish_fisher: number };
  };
  rebalance: { applied: boolean; volatility_change: number; turnover: number };
}

const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (!r.ok) {
    const err = (await r.json().catch(() => ({}))) as { error?: string };
    throw new Error(err.error ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

export const api = {
  assets: () => get<{ assets: Asset[] }>("/api/assets"),
  scenarios: () => get<{ scenarios: Scenario[] }>("/api/scenarios"),
  stressTest: (weights: Record<string, number>, scenario_id: string) =>
    post<StressResult>("/api/portfolio/stress-test", { weights, scenario_id }),
};
