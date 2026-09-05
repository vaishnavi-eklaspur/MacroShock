# Contributing to MacroShock

Thanks for your interest in MacroShock. It is an open-source (Apache-2.0) analytics platform,
and contributions — bug reports, reproducibility issues, documentation, or code — are welcome.

The guiding principle of this project is **reproducibility**: any result the engine reports must
be re-derivable by someone else, on another machine, from the code and the pinned data snapshot.
Please keep that property intact in anything you submit.

## Ground rules

- **Be able to reproduce it.** A bug report is far more useful with the exact portfolio weights,
  scenario, and commit SHA that produced the number.
- **No silent numerical changes.** If a change moves a published figure (R², a VaR, a drawdown),
  say so explicitly in the PR description and explain *why* the new number is more correct.
- **Determinism is a feature.** The synthetic generator is seeded (`RANDOM_SEED`) and the cache is
  keyed by `MODEL_VERSION`. Don't introduce unseeded randomness, wall-clock dependence, or
  iteration-order dependence into anything that affects a result.
- **Bump `MODEL_VERSION`** (`backend/data/reference.py`) when you change the model or reference
  data. The cache key embeds it, so a recalibration can never serve a stale number.

## Development setup

```bash
# Backend (Python 3.11+)
cd backend
pip install -r requirements.txt
python -m data.seed                  # build the SQLite store
flask --app app run -p 5050

# Analysis dashboard (runs the engine in-process; no API needed)
cd frontend && pip install -r requirements.txt
streamlit run streamlit_app.py

# Whole stack in containers
docker compose up --build
```

## Before you open a pull request

Run what CI runs. Every one of these is a merge gate:

```bash
cd backend && pytest -q                    # unit + API tests, coverage gate at 75%
python ../scripts/verify_math.py           # dependency-free re-derivation of every formula
ruff check . --select E9,F63,F7,F82        # lint
cd ../frontend-react && npm ci && npm run build   # type-check + build
helm lint charts/macroshock                # chart must lint and render
```

The pipeline (`.github/workflows/ci.yml`) additionally boots the full stack in Docker, renders and
schema-validates the Helm chart with `kubeconform`, and runs dependency scanning (`pip-audit`,
`npm audit`). A PR that breaks any of these will not merge.

### The math-verification gate

`scripts/verify_math.py` re-implements the core formulas using only the Python standard library
and asserts the engine agrees. It exists so a numerical regression cannot hide behind the same
library that produced it. **If you change a formula, update this script too** — and if you can't
re-derive your change independently, that is a strong signal the change needs more thought.

## Style

- Match the surrounding code; keep comments about *why*, not *what*.
- Public analytics functions are pure where practical: inputs in, arrays/dicts out, no I/O.
- New non-trivial logic ships with at least one meaningful test.
- Document any methodology change in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Reporting security issues

Please do **not** open a public issue for a security problem. Contact the maintainer directly; see
[`SECURITY_AUDIT.md`](SECURITY_AUDIT.md) for the project's current posture and known limitations.

## Licence

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE) that covers this project.
