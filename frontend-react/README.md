# MacroShock — React + TypeScript client

A typed React front-end for the MacroShock API, alongside the Streamlit dashboard. It exists
to demonstrate the TypeScript/UI side of the stack: a **typed API client** (`src/api.ts` mirrors
the JSON contract with interfaces) and a working stress-test view (weight sliders → scenario →
drawdown, factor-attribution bars, commentary).

## Run

```bash
# 1. Start the backend (from ../backend): flask --app app run -p 5050   # :5050
# 2. Then:
cd frontend-react
npm install
npm run dev        # http://localhost:5173  (Vite proxies /api -> :5050)
```

Type-check / production build:

```bash
npm run build      # tsc (strict) + vite build
```

Config: `VITE_API_BASE` (defaults to same-origin via the dev proxy) and `VITE_API_KEY`
(sent as `X-API-Key` if the backend requires it).

## Why both UIs?

Streamlit is the fast internal-tool dashboard; this shows the same engine driven from a
strictly-typed React client — the production, client-facing UI pattern (TypeScript, component
state, typed API boundary).
