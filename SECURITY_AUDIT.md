# MacroShock — Security & Production-Readiness Audit

**Stack:** Python/Flask + SQLite (mock Snowflake) · Streamlit · React/TypeScript (Vite) · Go CLI ·
Celery/Redis · S3-compatible object storage · Docker · Kubernetes/Helm
**Date:** 2026-09-05 · **Commit at audit:** `57a86df` + the fixes recorded below

This document records what was **tested** and what was **addressed**. It does not claim the
application is "secure" or "leakproof" — it states the specific checks performed, the fixes
applied, and the gaps deliberately left open (see *Known Limitations*).

---

## Summary table

| # | Category | Finding | Severity | Status |
|---|----------|---------|----------|--------|
| 1 | Secrets & credentials | Full git-history scan: no keys, tokens, or private keys ever committed | — | Verified clean |
| 1 | Secrets & credentials | `.env` gitignored, never committed; `.env.example` holds only `change-me` | — | Verified |
| 1 | Secrets & credentials | All secrets read from env; K8s consumes the API key from a `Secret` | — | Verified |
| 2 | Dependencies (pip) | `pip-audit`: **0 vulnerabilities** across all backend packages | — | Verified |
| 2 | Dependencies (npm) | Production bundle: **0 vulnerabilities** | — | Verified |
| 2 | Dependencies (npm) | `esbuild`/`vite` dev-server advisories | Moderate | **Fixed** (vite 5→8, plugin 4→6; audit now 0) |
| 3 | Auth & session | Write/delete gated by `X-API-Key`, constant-time compare, **fail-closed** | — | Verified (403 tested) |
| 3 | Auth & session | No passwords/JWT/session cookies exist — stateless analysis service | — | N/A by design |
| 4 | Injection — SQL | All queries parameterized (`?`); no string-built SQL | — | Verified |
| 4 | Injection — XSS | Streamlit auto-escapes; no `unsafe_allow_html=True`; React escapes by default | — | Verified |
| 4 | Injection — cmd/SSRF | No `eval`/`exec`/shell; outbound calls only to hardcoded tickers | — | Verified |
| 5 | Transport | Strict CSP (`default-src 'none'`), nosniff, X-Frame DENY, Referrer-Policy, HSTS-on-HTTPS | — | **Fixed** (earlier pass) |
| 5 | Transport | Per-IP rate limiting via ProxyFix + Redis, in-process fallback | — | Verified |
| 6 | Errors & logging | Validation errors crashed to 500 (pydantic `ctx` not serializable) | Medium | **Fixed** + regression test |
| 6 | Errors & logging | `debug=False`; catch-all returns generic JSON 500; logs carry no PII | — | Verified |
| 7 | Data protection | App stores **no PII** — weight vectors + public market data only | — | Verified |
| 8 | Config hygiene | Non-root containers; `.coverage` untracked; env-driven config | — | **Fixed** (earlier pass) |
| 9 | Code quality | 83 Python + 9 Go tests; 9-job CI; 60+ incremental commits | — | Verified |
| **10** | **Container hygiene** | **`backend/.dockerignore` missing** — `COPY . .` baked tests, caches and any local SQLite DB into the published image | **Medium** | **Fixed** |
| 10 | Container hygiene | `minio/minio:latest` — unpinned, drifts silently | Low | **Fixed** (pinned release) |
| 10 | Container hygiene | Base images were tag-pinned, not digest-pinned | Low | **Fixed** (digest-pinned + Dependabot keeps them fresh) |
| 10 | Container hygiene | React image ran nginx's master as root | Low | **Fixed** (`nginx-unprivileged`, uid 101, :8080) |
| 10 | Container hygiene | K8s CPU/memory requests+limits set on both workloads | — | Verified |
| **11** | **Frontend build secrets** | **`VITE_API_KEY` read in `api.ts` and documented in the README — `VITE_*` is compiled into the public bundle, so the key would ship to every browser** | **High** | **Fixed** (removed entirely) |
| 11 | Frontend build secrets | Production source maps not emitted (Vite default) | — | Verified |
| 11 | Frontend build secrets | Streamlit dashboard no longer reads any API key (runs in-process) | — | Verified |
| 12 | Business logic | Mass assignment: explicit pydantic schemas; workflow spec is `extra="forbid"`; no ORM binding | — | Verified |
| 12 | Business logic | Concurrency: the single write path is an atomic `ON CONFLICT DO UPDATE` upsert | — | Verified |
| 12 | Business logic | BOLA: no per-user resources exist (single-tenant) | Low | Flagged (by design) |
| **13** | **Repo integrity** | **`cli/go.sum` was not committed** — Go dependency integrity unpinned; CI regenerated it with `go mod tidy` instead of enforcing it | **Medium** | **Fixed** (committed + CI enforces & drift-checks) |
| **13** | **Repo integrity** | **CI workflows had no `permissions:` block** — `GITHUB_TOKEN` ran at default scope | **Medium** | **Fixed** (`contents: read`) |
| 13 | Repo integrity | `package-lock.json` committed; CI installs via `npm ci` | — | Verified |
| **14** | **Artifact sweep** | **`.claude/` named in `.gitignore`/`.dockerignore` disclosed the tooling used** | Low | **Fixed** (generic `.*` rule + local `.git/info/exclude`) |
| 14 | Artifact sweep | No TODO/FIXME/placeholder comments, no swallowed exceptions, no dead code | — | Verified |
| **15** | **Production leaks** | **`Server:` header disclosed gunicorn/Werkzeug versions** | Low | **Fixed** (overridden) |
| 15 | Production leaks | No Swagger/GraphQL introspection, no file uploads, no user-supplied redirects | — | N/A |
| 15 | Production leaks | `/health` disclosed component wiring to anonymous callers | Low | **Fixed** (minimal unless authenticated) |

---

## Interview-ready explanations (new categories)

### 10 — Container & infrastructure hygiene
The backend image is built with `./backend` as its context and does `COPY . .`, and there was **no
`backend/.dockerignore`** — the root one doesn't apply to a nested build context. That meant the
test suite, `__pycache__`, coverage data and, more importantly, any **local SQLite database** a
developer had lying around would be baked into a published image. I added a context-specific
ignore file so the image contains only what actually runs. I also pinned `minio/minio` to a
release tag, because `:latest` means the image you tested is not necessarily the image you deploy.
Both workloads already ran as an unprivileged uid 10001 with `allowPrivilegeEscalation: false`,
dropped capabilities, and explicit CPU/memory requests and limits in the Helm chart.
**Interview line:** *"A nested build context needs its own `.dockerignore` — the root one doesn't
apply, and without it I was shipping tests and a stray local database inside a public image."*

### 11 — Frontend & build-time secrets *(the most serious finding)*
The React client read `VITE_API_KEY` and attached it as an `X-API-Key` header — and the README
documented it as configuration. **Anything a Vite build can read is compiled into the JavaScript
bundle**, so that "secret" would be published to every visitor: open devtools, read the key, and
you can write to and delete from the persistence API. It was also entirely unnecessary — the React
client only calls open read/compute endpoints and never touches a key-gated route. I removed the
key path, its type declaration, and the README line that invited someone to set it. I also
confirmed Vite emits no production source maps, so the internal API shapes aren't handed out.
**Interview line:** *"A key in a browser bundle isn't a secret, it's a publication. The client
didn't need one, so the fix was deleting the capability rather than trying to hide it."*

### 12 — Business logic & data integrity
There is no ORM and no mass-assignment surface: every request is parsed into an explicit pydantic
schema with declared fields, and the workflow specification uses `extra="forbid"` so a typo or an
injected field fails loudly instead of being silently absorbed. The only endpoint that mutates
shared state is the portfolio upsert, which is a single atomic `INSERT … ON CONFLICT DO UPDATE`,
so concurrent saves of the same name can't interleave into a corrupt row. Broken object-level
authorization genuinely doesn't apply yet — there are no per-user resources to confuse — but I've
recorded it as a limitation rather than a clean bill of health.
**Interview line:** *"There's no mass-assignment risk because nothing binds raw JSON to a model —
every field is declared, and unknown fields are rejected rather than ignored."*

### 13 — Dependency & repository integrity
Two real gaps. First, **`cli/go.sum` was never committed** even though the CLI depends on
`gopkg.in/yaml.v3`, and CI ran `go mod tidy` — which *rewrites* the lockfile rather than enforcing
it, so builds weren't verified against pinned hashes. I committed `go.sum` and changed CI to
`go mod download && go mod verify`, plus a step that fails if `go mod tidy` would change anything
(lockfile-drift detection). Second, the CI workflows declared **no `permissions:` block**, so
`GITHUB_TOKEN` ran at the repository default scope; both are now `contents: read`, with only the
image-publishing workflow holding `packages: write`.
**Interview line:** *"`go mod tidy` in CI isn't lockfile enforcement — it's lockfile laundering.
I switched to `download`+`verify` and made drift a build failure."*

### 14 — Artifact sweep
No placeholder comments, no `TODO`/`FIXME`, no exception handlers that swallow errors, no dead or
duplicated code paths. The one real hit was self-inflicted: I had added `.claude/` to `.gitignore`
and `.dockerignore`, which **discloses the tooling used** in a repository meant to stand on its own.
I replaced it with a generic rule that excludes *all* dotted entries from the Docker context (which
is more robust anyway — any future stray dot-directory is excluded automatically) and moved the git
ignore to `.git/info/exclude`, which is local and never committed. Protection kept, disclosure gone.

### 15 — Miscellaneous production leaks
There is no Swagger/OpenAPI endpoint, no GraphQL introspection, no file-upload path, and no
endpoint that redirects to a user-supplied URL, so those classes don't apply. The API did return a
`Server:` header advertising gunicorn/Werkzeug and their versions, which tells an attacker exactly
which CVE list to work through for nothing in return — it's now overridden. `/health` deliberately
reports the model version and which optional components are wired up, because Kubernetes probes and
operators need it; it contains no secrets and no stack traces, and I've recorded it as an accepted
disclosure rather than pretending it isn't one.

---

## Known Limitations (not fixed — by scope or deliberate decision)

1. **No authentication or authorization system.** Saved portfolios are global, not per-user. This
   is a single-tenant analysis service, not a multi-user product. If it became multi-user it needs
   real identity plus per-user ownership checks on `/api/portfolios/<name>` to prevent BOLA/IDOR.
   *Note this is also the pattern REANA itself uses (`REANA_ACCESS_TOKEN`); adding JWT here would
   mean standing up a mock auth server that protects nothing.*

2. **CORS is `*` on the read/compute API.** Correct for a public read API that uses no cookies or
   credentials — `*` is only dangerous when combined with credentialed requests. `CORS_ORIGINS`
   already accepts an explicit allowlist if that ever changes.

3. **`/metrics` is unauthenticated.** It exposes request counters and latency histograms, no
   secrets. It is *not* internet-reachable in the Kubernetes deployment: the ingress routes only
   `/` and `/api`, so `/metrics` is cluster-internal. Gating it behind the API key would break
   Prometheus Operator scraping, which cannot send arbitrary headers; a NetworkPolicy is the
   idiomatic control if stricter isolation is wanted.

4. **No encryption at rest, and SQLite stands in for a warehouse.** Justified by what is stored:
   only public market data and non-sensitive weight vectors. A production Snowflake/Postgres
   deployment should add at-rest encryption, a least-privilege role, and a managed secret store.

5. **`.claude/` appears in the *history* of `.gitignore`.** The working tree and all current files
   are clean. Rewriting published history with `filter-repo` for a single ignore line would
   invalidate every commit SHA and force-push a public repository — a poor trade, so it is
   recorded here rather than scrubbed.

*Closed since the previous pass:* the React bundle no longer carries an API key; `backend/.dockerignore`
added; `cli/go.sum` committed and CI enforces it; CI tokens scoped to `contents: read`; server
version banner suppressed; MinIO and every base image pinned (digests + Dependabot); the React image
runs unprivileged; `vite` upgraded to 8 (npm audit clean); `/health` discloses nothing to anonymous
callers.
