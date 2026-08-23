# MacroShock — Security & Production-Readiness Audit

**Scope:** Flask API (`backend/`), Streamlit dashboard (`frontend/`), React/TypeScript client
(`frontend-react/`), and deployment configs (Docker, Render, Azure, CI).
**Date:** 2026-08-23 · **Commit at audit:** `c191250`

This document records what was **tested** and what was **addressed**. It does not claim the
application is "secure" or "leakproof" — it states the specific checks performed, the fixes
applied, and the gaps left open (see *Known Limitations*).

---

## Summary table

| # | Category | Finding | Severity | Status |
|---|----------|---------|----------|--------|
| 1 | Secrets & credentials | Full git-history scan (50 commits) found no hardcoded keys/tokens/private keys | — | Verified clean |
| 1 | Secrets & credentials | `.env` gitignored and never committed; only `.env.example` (placeholder `change-me`) | — | Verified |
| 1 | Secrets & credentials | Secrets read from env (`MACROSHOCK_API_KEY`); Render `sync:false`, Azure `secretref` — none baked into code | — | Verified |
| 2 | Dependencies (npm) | Production bundle: **0** known vulnerabilities | — | Verified |
| 2 | Dependencies (npm) | `nanoid` (high) + `postcss` (moderate) in build toolchain | High/Mod | **Fixed** (`npm audit fix`) |
| 2 | Dependencies (npm) | `esbuild`/`vite` dev-server advisories (dev-only, not shipped) | Moderate | Flagged (needs breaking `vite@8`) |
| 2 | Dependencies (pip) | `pip-audit` could not complete in the audit env (network timeouts) | — | Flagged (run in CI) |
| 3 | Auth & session | Write/delete persistence gated by `X-API-Key`, constant-time `hmac.compare_digest`, fail-closed when unset | — | Verified (403 confirmed) |
| 3 | Auth & session | No user accounts / passwords / JWT / session cookies exist | — | N/A by design |
| 3 | Auth & session | Saved portfolios are global (no per-user ownership) | Low | Flagged (limitation) |
| 4 | Injection — SQL | All queries parameterized (`?` placeholders) in `database.py`, `seed.py` | — | Verified |
| 4 | Injection — XSS | Streamlit escapes by default; no `unsafe_allow_html=True`; the one `st.html()` is a static footer | — | Verified |
| 4 | Injection — cmd | No `eval`/`exec`/`os.system`/`subprocess`/`shell=True` anywhere | — | Verified |
| 4 | Injection — SSRF | Outbound requests only to hardcoded tickers / env-set base — never user-controlled URLs | — | Verified |
| 4 | Input validation | Pydantic bounds on every POST body (finite, non-negative, ranged, length-capped) | — | Verified |
| 5 | Transport | Security headers were absent | Medium | **Fixed** (nosniff, DENY, CSP, Referrer-Policy, HSTS) |
| 5 | Transport | Rate limiting per real client IP (ProxyFix + Redis, in-proc fallback) | — | Verified |
| 5 | Transport | CORS `*` on read/compute API | Low | Verified acceptable (no cookies/credentials) |
| 6 | Errors & logging | `debug=False`; error handlers return controlled JSON, no stack traces to client | — | Verified |
| 6 | Errors & logging | Logs contain method/path/status/latency only — no PII/secrets | — | Verified |
| 7 | Data protection | App stores **no PII** — only weight vectors + public market-return history | — | Verified |
| 7 | Data protection | SQLite mock DB; no superuser network connection string | — | Verified / N/A |
| 8 | Config hygiene | `backend/.coverage` (build artifact) was tracked in git | Low | **Fixed** (untracked + gitignored) |
| 8 | Config hygiene | Docker images ran as root | Medium | **Fixed** (non-root user in both) |
| 8 | Config hygiene | `.gitignore` covers `.env`, DBs, `node_modules`, `dist`; README has no live creds | — | Verified |
| 9 | Code quality | 52 tests / 12 files; CI coverage gate `--cov-fail-under=75` (~79% actual) | — | Verified |
| 9 | Code quality | CI: math-verify, test matrix (3.11/3.12) + ruff, React `tsc` build, docker-smoke | — | Verified |
| 9 | Code quality | 50 commits, incremental & descriptive — not a single squash | — | Verified |

---

## Interview-ready explanations (per fix / finding)

### 1 — Secrets & credentials
I scanned the entire git history (`git log --all -p`, not just the working tree) for key/token/
private-key patterns and found none — the only hits were the *words* "secret"/"token" in docs and
variable names. `.env` is gitignored and was never committed; the repo ships only `.env.example`
with a `change-me` placeholder. Every secret is read from an environment variable at runtime
(`os.getenv("MACROSHOCK_API_KEY")`), injected as a Render "sync:false" secret or an Azure Container
Apps `secretref` — never a default baked into code. **Interview line:** "No secret has ever been in
the repo. Config comes from the environment; the deploy platforms inject the API key as a managed
secret, and history is clean, so there's nothing to rotate or scrub."

### 2 — Dependency vulnerabilities
`npm audit --omit=dev` reports **zero** vulnerabilities in the code that actually ships to the
browser (React/React-DOM). The advisories that existed were all in the build toolchain; I applied
the non-breaking ones (`nanoid` high, `postcss` moderate) with `npm audit fix` and left the
`esbuild`/`vite` ones flagged because clearing them needs a breaking `vite@8` upgrade and they only
affect the local dev server, never the deployed static bundle. `pip-audit` didn't finish in the
audit environment (repeated network timeouts resolving the tree), so I flagged it to run in CI
rather than hand-wave a result. **Interview line:** "I separated 'what ships' from 'what builds' —
the shipped bundle is clean; the remaining findings are dev-only and I documented the breaking
upgrade instead of forcing it blind."

### 3 — Authentication & session handling
There is no user/password/JWT system — this is a stateless analytics service — so the usual
password-hashing and cookie-flag checks are N/A. The one privileged surface is portfolio
persistence: `POST`/`DELETE /api/portfolios` require an `X-API-Key` compared with
`hmac.compare_digest` (constant-time, immune to timing attacks) and are **fail-closed** — when no
key is configured they return 403, so a public instance can never be written to. I confirmed this
with a live test (POST without a key → 403). **Interview line:** "Writes are constant-time
key-gated and fail closed; reads and compute stay open because the demo needs them, and they're
protected by per-IP rate limiting instead."

### 4 — Input validation & injection
Every SQL statement is parameterized (`?` placeholders) — no string-concatenated SQL. Every POST
body goes through a Pydantic schema that enforces finite numbers, non-negative long-only weights,
bounded confidence/target-loss, and length-capped names, so malformed or hostile payloads are
rejected with a clean 400 before touching the engine. There is no `eval`/`exec`/`subprocess`/shell
usage, so there's no command-injection surface, and the only outbound calls go to hardcoded Yahoo
tickers — never a user-supplied URL — so there's no SSRF vector. On the UI side, Streamlit escapes
output by default, nothing uses `unsafe_allow_html=True`, and the single raw-HTML block is a static
footer with no user input. **Interview line:** "Injection is closed off structurally: parameterized
SQL, schema-validated inputs, no shell, no user-controlled URLs, and an auto-escaping UI."

### 5 — API & transport security
The API previously set no security headers. I added them on every response:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and —
because the service returns only JSON, never HTML — a maximally strict
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. HSTS is emitted only when the
request arrived over HTTPS (read from the proxy's `X-Forwarded-Proto` via `ProxyFix`), so local HTTP
dev is unaffected. Rate limiting keys on the real client IP (not the proxy) and is Redis-backed with
an in-process fallback. CORS is `*` on the read/compute API, which is safe here specifically because
no cookies or credentials are involved — `*` is only dangerous when combined with credentialed
requests. **Interview line:** "Because it's a pure JSON API I could lock the CSP all the way down to
`default-src 'none'`, and I gated HSTS on actual HTTPS so I'm not breaking local dev."

### 6 — Error handling & logging
`debug` is `False` and production runs under gunicorn, so no interactive debugger or stack trace is
ever exposed to a client. Custom error handlers turn validation/value/lookup errors into controlled
JSON messages (400/404) instead of leaking internals. Request logging records only
method/path/status/latency — no request bodies, no PII, no secrets. **Interview line:** "Clients get
clean, generic errors; the detail stays in server logs, and the logs never contain sensitive data."

### 7 — Data protection
The app stores **no personal data at all** — the only persisted state is portfolio weight vectors
(ticker → number) and public weekly market-return history. That's the strongest form of data
protection: the data that isn't collected can't leak. There's no superuser database connection
string; the store is a file-based SQLite standing in for a Snowflake/Postgres warehouse.
**Interview line:** "The least-risky PII is the PII you never store — this app keeps none, so
encryption-at-rest and data-subject concerns are largely moot by design."

### 8 — Config & deployment hygiene
Both Docker images now run as a dedicated non-root `appuser` (least privilege) — if the process were
ever compromised, it has no root in the container. I found `backend/.coverage` (a test-run artifact)
committed to git and removed it from tracking plus added it to `.gitignore`. Configuration is
entirely environment-driven with an `.env.example` template, dev vs prod differ only by env vars, and
the README contains no real credentials. **Interview line:** "Containers drop root, config is
env-var driven with a documented example, and I cleaned a build artifact that had slipped into
version control."

### 9 — Code-quality signals
52 tests across 12 files, with CI enforcing a coverage floor (`--cov-fail-under=75`, ~79% actual).
CI runs an independent from-scratch math verification, the test suite on a Python 3.11/3.12 matrix
with `ruff` linting, a `tsc` type-check + build of the React client, and a docker-smoke job that
boots the whole stack and asserts it serves. The history is 50 incremental commits with descriptive
messages — not a single squashed "final" commit. **Interview line:** "The CI doesn't just run tests
— it independently re-derives the math, type-checks the frontend, and boots the full stack in Docker,
so a broken deploy can't reach main."

---

## Known Limitations (not fixed — by scope, time, or a decision you should make)

1. **`pip-audit` was not completed in this environment.** Network resolution timed out repeatedly.
   *Action:* add a `pip-audit` step to CI. Independently, the pinned `flask-cors==4.0.1`,
   `gunicorn==22.0.0`, and `flask==3.0.3` all have newer patch releases addressing later advisories
   — worth upgrading behind the test suite (not applied here because I couldn't run the authoritative
   audit to confirm, and the API sits behind a platform TLS proxy that mitigates request-smuggling).

2. **Two npm dev-toolchain advisories remain** (`esbuild`/`vite`). Clearing them requires a breaking
   `vite@8` upgrade. They affect only the local dev server, never the deployed bundle, so I flagged
   rather than force-upgraded.

3. **No authentication/authorization system.** Saved portfolios are global, not per-user — this is a
   single-tenant demo, not a multi-user product. If it became multi-user, add real auth and per-user
   ownership checks on `/api/portfolios/<name>` to prevent IDOR.

4. **CORS is `*` on the read/compute API.** Safe today because no cookies/credentials are used; if
   credentialed requests are ever introduced, replace `*` with an explicit origin allowlist
   (`CORS_ORIGINS` already supports this).

5. **`/metrics` is unauthenticated** (Prometheus counters by route/status). Low sensitivity, but in a
   real deployment put it behind network policy or auth.

6. **No encryption at rest.** Justified by #7 — the store holds only public market data and
   non-sensitive weight vectors.

7. **SQLite stands in for a production warehouse.** A real Snowflake/Postgres deployment should use a
   least-privilege database role and a managed secrets store, not a single connection principal.

8. **No catch-all 500 handler.** Unexpected exceptions return Flask's default (generic when
   `debug=False`, so no leak), but a JSON 500 handler would make error responses uniform.
