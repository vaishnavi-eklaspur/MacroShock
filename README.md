# MacroShock

**A multi-asset stress-testing and portfolio-construction engine.** Given a portfolio and a
macro shock, it decomposes *why* the portfolio breaks (which factors, which holdings,
regime-aware), quantifies the *tail*, measures the book *against a benchmark* (tracking error,
active risk, factor tilts), and proposes a *constrained* mitigation trade — the vocabulary of
an institutional risk desk, in a small, tested, deployable stack.

[![CI](https://github.com/vaishnavi-eklaspur/MacroShock/actions/workflows/ci.yml/badge.svg)](https://github.com/vaishnavi-eklaspur/MacroShock/actions/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-79%25-brightgreen)
![tests](https://img.shields.io/badge/tests-54%20passing-brightgreen)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![helm](https://img.shields.io/badge/Helm-chart-0f1689)

**▶ Live demo: [macroshock.streamlit.app](https://macroshock.streamlit.app)** — a self-contained dashboard running the analytics engine in-process.

> Educational demonstration on real market data — **not** investment advice, **not** a
> regulatory-grade system. Its limits are stated explicitly below and in
> [`docs/DESIGN_AND_MATH.md`](docs/DESIGN_AND_MATH.md).

---

## Reproducibility by construction

The engine is a **deterministic computational workload**: the same inputs must yield bit-identical
outputs on any machine, or the analysis is worthless. That property is engineered, not assumed:

| Mechanism | Where | What it guarantees |
|---|---|---|
| **Pinned inputs** | `backend/data/real_*.csv` | The published results run against a committed, immutable market-data snapshot — not a live feed that changes under you. Provenance (source, window, week count) is recorded in `dataset_meta` and served at `/api/meta`. |
| **Seeded generation** | `RANDOM_SEED` in `data/reference.py` | The synthetic two-regime generator is fully seeded; regenerating the dataset reproduces it exactly. |
| **Model versioning** | `MODEL_VERSION` in the cache key | A recalibration can never serve a stale cached number — changing the model invalidates every prior entry by construction. |
| **Pinned environment** | exact `==` pins + Docker images | The same dependency set and the same image run locally, in CI, and in Kubernetes. |
| **Independent re-derivation** | `scripts/verify_math.py` (CI gate) | Every core formula is re-implemented using only the Python standard library and asserted against the engine — so a numerical regression cannot hide behind the same library that produced it. |
| **Executable environment** | `charts/macroshock/`, `docker compose` | The whole platform is declarative: one `helm install` reproduces the running system, not just the numbers. |

This is why the out-of-sample backtest below reports a *negative* skill score rather than a
flattering one: the pipeline is built so results can't be quietly tuned, and the honest number is
the one that survives.

---

## Analyses as code — declarative workflows

An analysis is not a sequence of clicks or ad-hoc API calls: it is a **specification you can
version, review and re-run**. MacroShock accepts a `macroshock.yaml` describing the inputs, the
pipeline and the outputs, and executes it.

```yaml
inputs:
  data:                                  # pinned snapshot => reproducible
    source: csv
    asset_returns: backend/data/real_asset_returns.csv
  portfolio: {SPY: 0.20, IEF: 0.15, GLD: 0.09, ...}
workflow:
  type: serial
  steps:
    - {name: risk-attribution, run: risk-contribution}
    - {name: gfc-2008,         run: stress-test, with: {scenario_id: GFC_2008}}
    - {name: out-of-sample-backtest, run: backtest}
```

```bash
cd backend
python -m workflow validate ../macroshock.yaml     # schema check, no computation
python -m workflow run      ../macroshock.yaml --output ../results
```

Every step writes a JSON artifact, and `summary.json` records the provenance needed to reproduce
the run — **spec digest, model version, dataset source/window, and per-step timings**:

```json
{ "spec_digest": "06ddc60d2a361007", "model_version": "4.0.0",
  "dataset": {"source": "csv", "as_of_start": "2015-01-09", "as_of_end": "2026-07-17",
              "n_weeks": "602", "factors": "independent"} }
```

Validation is strict and happens *before* any computation — unknown fields, duplicate step names,
unknown tickers and missing step parameters all fail loudly rather than producing a partial run.
CI validates and executes the shipped spec on every push.

### Submitting as a job (Go CLI + async workers)

A full analysis is a compute job, not an HTTP request to hold open. `POST /api/workflows`
validates the spec synchronously and returns **202 + a job id**; a Celery worker executes it and
`GET /api/jobs/<id>` reports progress. With no broker configured the job runs in-process and the
record says `"mode": "inline"` — the API never claims work was distributed when it was not.

A small **Go** CLI is the operator-facing front end. It parses and validates the spec locally
(instant, precise errors — reporting *every* problem at once rather than the first), then
forwards the original document to the API:

```bash
cd cli && go build -o macroshock-cli .

./macroshock-cli validate ../macroshock.yaml
./macroshock-cli submit   ../macroshock.yaml --api http://localhost:5050 --wait
./macroshock-cli status   <job-id>
```

Validation is deliberately duplicated in Go and Python: the client fails fast for the author,
and the server re-validates because a client is never a trust boundary.

### Real-time completion events (optional)

Polling `GET /api/jobs/<id>` is the reliable baseline. With `MACROSHOCK_ENABLE_REALTIME=1` the API
also pushes a `job_completed` event over Socket.IO, so a client learns the instant a run finishes:

```js
const socket = io(API_BASE);
socket.emit("subscribe", { job_id: jobId });
socket.on("job_completed", ({ result }) => setSummary(result));
```

It is **off by default and contained on purpose**: `threading` async mode rather than eventlet, so
nothing monkey-patches a process doing numerical work (set `MACROSHOCK_SOCKETIO_ASYNC_MODE=eventlet`
with a matching gunicorn worker for a true WebSocket upgrade; otherwise Socket.IO negotiates
long-polling). When a Redis message queue is configured, a Celery worker publishes the event and
the API process relays it. A failed notification is swallowed — it can never fail the job that
produced it.

### Artifacts in object storage

A finished analysis produces *files*, and they need to outlive the request. When an S3-compatible
endpoint is configured, every artifact is published to it and the response carries time-limited
presigned URLs:

```bash
export MACROSHOCK_S3_ENDPOINT=http://localhost:9000     # MinIO in docker compose
export MACROSHOCK_S3_ACCESS_KEY=macroshock MACROSHOCK_S3_SECRET_KEY=macroshock123
```

`boto3` against a plain S3 endpoint is used deliberately rather than a vendor SDK, so the same
code targets **MinIO** locally, **AWS S3**, or **Ceph/RadosGW** — the deployment target is
configuration, not a code change. Publication is strictly additive: if the object store is down,
the run still succeeds, the results stay on disk, and the summary records `artifact_error`
rather than failing a computation that already produced correct numbers.

### Running it on REANA

The same spec runs unchanged on [REANA](https://reanahub.io), CERN's reproducible-analysis
platform, via [`reana.yaml`](reana.yaml) — the workflow executes inside the published container
image against the committed data snapshot:

```bash
reana-client create -f reana.yaml -n macroshock
reana-client upload -w macroshock && reana-client start -w macroshock
reana-client download results/summary.json -w macroshock
```

---

## It fits the model, not the noise

The quickest way to see the engine is real: seeded on live market data (2015–present), the
factor betas are **estimated by OLS** and recover known economic structure — not curve-fit.

| Holding | Estimated exposure | Ground truth |
|---|---|---|
| IEF (7–10y Treasury) | Rates **−7.31** | ≈ its ~7.5y effective duration |
| TLT (20y+ Treasury) | Rates **−15.75** | ≈ its ~17y duration |
| SPY | Equity **1.00** | it *is* the market |
| GLD / EEM / EFA | FX **−0.84 / −0.66 / −0.70** | all fall against a strong USD |

Mean R² ≈ **0.79** on real weekly data — deliberately *not* ~1.0. The factors are independent
series (real proxies or a projection-free CSV), so a genuine share of return stays
idiosyncratic. If the factors were derived from the assets, R² would be ~1.0 and the "factor
model" would be circular — a trap the code explicitly tests against.

## The backtest — honest, not flattering

The single most telling number, reported plainly rather than buried:

- **In-sample (pricing check):** given each crisis's calibrated factor shocks, the model
  reproduces realized asset returns to **4–12% MAE**. The conditional-pricing claim holds.
- **Out-of-sample (leave-one-crisis-out):** betas fit *only* on the weekly history predict a
  held-out crisis. Across five heterogeneous crises the model shows **negative skill** vs. the
  naive benchmarks (predict-zero, repeat-last-crisis) — it does **not** forecast the next
  crisis's shape, and the report says so.

That's the point: forecasting *which* crisis happens isn't the tool's claim; pricing the impact
*given* a scenario is — and that is what the in-sample check and the risk/attribution outputs
validate. A model that quietly beat every benchmark out-of-sample on five crises would be the
thing to distrust.

## What makes it more than a stock tracker

- **Regime-conditional risk attribution.** MCTR/CCTR decomposition (Euler identity, with
  block-bootstrap confidence intervals) shows a 40% *capital* weight can be 70% of the *risk* —
  and that the risk share **shifts** from the calm to the crisis regime as correlations tighten.
- **Benchmark-relative analytics** — tracking error (calm *and* crisis), active-risk
  contribution, factor tilts and active share vs. a strategic benchmark. This is how multi-asset
  model portfolios are actually managed: relative to a benchmark, not in absolute terms.
- **Fat-tailed risk done honestly.** Gaussian VaR sits next to Historical, Cornish–Fisher and
  Student-t VaR/CVaR, with a Jarque–Bera normality test and a validity check on the CF
  expansion — because a stress tool that assumes normality is a contradiction.
- **Reverse stress testing.** Solves for the *most plausible* (bounded, sign-constrained) joint
  factor shock that produces a target loss, scored by Mahalanobis distance, with ranked
  single-factor alternatives.
- **A backtest that can fail.** Leave-one-crisis-out across five documented crises (dot-com,
  GFC, Euro 2011, COVID, 2022), with betas fit only on the weekly history so they never see the
  crisis they predict. It reports skill vs. naive benchmarks **honestly** — including where the
  model has none, because forecasting the next crisis's shape is not what the tool claims to do.
- **Statistical rigor on display, not hidden** — constant-correlation Ledoit–Wolf shrinkage,
  chi-square regime detection (not a top-x% quantile), VIF and condition-number
  multicollinearity diagnostics, a model-versioned cache so a recalibration can never serve a
  stale number.

## Architecture

```
React + TS client ──REST→  Flask API  ──→  Redis cache (graceful fallback)
                           (pydantic,          │
                           rate-limited,       ▼
                           /metrics)     Analytics core (numpy/scipy) ──→ Data layer
Streamlit dashboard ─────────────────→  cov · VaR/CVaR · OLS betas       SQLite (or real
   (embeds the core in-process)         MCTR · reverse-stress · TE       Snowflake adapter)
```

The analytics core is a plain Python library: the **Streamlit dashboard embeds it in-process**
(so the live demo is a single self-contained app), while the **Flask API wraps the same core**
for the React client and any programmatic caller.

| Layer | Tech | Notes |
|---|---|---|
| UI | **Streamlit** dashboard (engine in-process) + **React/TypeScript** client (`frontend-react/`) over the Flask API | two independent front-ends, one analytics core |
| API | **Flask** + pydantic | validated, Redis-cached, API-key + rate-limited; **`prometheus_client`** counters + latency histogram at `/metrics` |
| Analytics | **Python / numpy / scipy** | pure, tested functions ([`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)) |
| Data | **SQL** — SQLite via a mock **Snowflake** connector | mirrors the real connector API (`cursor.execute`, `fetch_pandas_all`); swap for `snowflake-connector-python` in prod |
| Deploy | **Kubernetes + Helm** (`charts/macroshock/`) · **Streamlit Community Cloud** (self-contained dashboard) · **Azure Container Apps** · **Docker Compose** (local) | one `helm install` for a cluster; images published to GHCR by CI |
| Observability | **Prometheus** exposition + optional **ServiceMonitor** | pod scrape annotations out of the box; Prometheus Operator supported via `metrics.serviceMonitor.enabled` |

## Run it

```bash
docker compose up --build
```
Dashboard → <http://localhost:8501> · API → <http://localhost:5050> · React → <http://localhost:5173>

### On Kubernetes

The platform ships as a Helm chart. CI lints it, renders every feature path, schema-validates the
output with `kubeconform`, and publishes both images to GHCR — so what you install is what CI proved.

```bash
helm install macroshock ./charts/macroshock

# with Prometheus Operator scraping and an ingress:
helm install macroshock ./charts/macroshock   --set metrics.serviceMonitor.enabled=true   --set ingress.enabled=true --set ingress.host=macroshock.example.org   --set image.tag=v4.0.0
```

Both workloads run as an unprivileged user with `allowPrivilegeEscalation: false`, dropped
capabilities, resource limits, and startup/readiness/liveness probes. Portfolio persistence is
**fail-closed**: without `api.apiKeySecret`, write endpoints are disabled rather than left open.

<details>
<summary>Without Docker, real data, tests</summary>

```bash
# Backend (Python 3.11)
cd backend && pip install -r requirements.txt
python -m data.seed && flask --app app run -p 5050

# Real market data (falls back to synthetic if Yahoo is unreachable):
python -m data.seed --source yahoo --start 2015-01-01

# Streamlit dashboard  /  React client
cd frontend && pip install -r requirements.txt && streamlit run streamlit_app.py
cd frontend-react && npm install && npm run dev

# Tests + a dependency-free re-derivation of every formula
cd backend && pytest -q && python ../scripts/verify_math.py
```
</details>

## Universe & scenarios

**13 assets** across US/intl/EM equity, the Treasury curve (IEF/TLT/TIP), IG & HY credit, gold,
commodities and REITs. **8 scenarios** (2000 dot-com, 2008 GFC, 2011 Euro, 2013 taper, 2020
COVID, 2022 rate shock, plus synthetic inflation & stagflation) — or build any shock
interactively in the *Scenario builder* tab.

## Honest limitations

- **ETF-level, single-period linear pricing** — not security-level, no instrument cash flows or
  option greeks. This is a factor demo, not Aladdin.
- **On real data, Credit and Liquidity are proxies** (HY-excess and VIX); a licensed feed
  (Bloomberg OAS, a funding-stress series) is the production fix.
- **Five crises** is enough to be indicative out-of-sample, not statistically conclusive.
- The deployed dataset is a **committed real-data snapshot**, because Yahoo blocks datacenter
  IPs; the live `--source yahoo` path exists but can't run from a cloud host.

Naming these is the point: the engine is built to survive scrutiny, and *the how is as
important as the what*. Full derivations, calibration sources and the design rationale are in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and [`docs/DESIGN_AND_MATH.md`](docs/DESIGN_AND_MATH.md).
