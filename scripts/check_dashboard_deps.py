"""Guard the deployed dashboard's dependency contract.

The live dashboard (Streamlit Community Cloud) installs ONLY `frontend/requirements.txt`, yet it
imports the backend and runs the analytics engine in-process. Every other CI job installs the
full backend requirement set, so a new top-level backend import — pydantic, yaml, boto3, celery,
flask-socketio — would break the live app while CI stayed green.

This script reproduces the deployed environment: it must be run in an interpreter where only the
dashboard's dependencies are installed. It performs exactly what the dashboard does on first
load, so a missing dependency fails here instead of in production.

Run:  python scripts/check_dashboard_deps.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    # 1) Seed the store from the committed snapshot — the dashboard's `_load_engine` step 1.
    from data import seed

    db_path = os.path.join(tempfile.gettempdir(), "macroshock_depcheck.db")
    seed.seed(
        db_path=db_path,
        source="csv",
        csv_path=str(BACKEND / "data" / "real_asset_returns.csv"),
        factors_csv=str(BACKEND / "data" / "real_factor_returns.csv"),
    )

    # 2) Build the engine — step 2.
    from analytics.engine import MacroShockEngine

    engine = MacroShockEngine(db_path)

    source = str(engine.dataset_meta.get("source", "unknown"))
    if source.startswith("synthetic"):
        print(f"FAIL: expected the committed CSV snapshot, got '{source}'. "
              "The seeder fell back to synthetic data, so the deployed dashboard would "
              "silently show different numbers.")
        return 1

    # 3) Drive one real computation. Every analytics module is imported when
    #    analytics.engine is imported, so a single call exercises the whole chain.
    weights = {t: 1.0 / len(engine.tickers) for t in engine.tickers}
    engine.stress_test(weights, engine.list_scenarios()[0]["scenario_id"])

    print(f"PASS: the dashboard's engine path runs on frontend/requirements.txt alone "
          f"(source={source}, weeks={engine.dataset_meta.get('n_weeks')}).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError as exc:
        print(f"FAIL: the dashboard's import chain needs a package that is NOT in "
              f"frontend/requirements.txt -> {exc}")
        print("Either add it to frontend/requirements.txt or keep that import lazy/optional; "
              "otherwise the live Streamlit deployment will crash on load.")
        raise SystemExit(1)
