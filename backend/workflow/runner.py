"""Execute a validated `MacroShockSpec` against the analytics engine.

Each step maps to one engine call and writes a JSON artifact; a `summary.json` records the
provenance needed to reproduce the run (spec digest, dataset provenance, model version, per-step
timing). Nothing here talks HTTP — the same spec runs identically on a laptop, inside the
container image, or as a REANA workflow step.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .spec import DataSpec, MacroShockSpec, StepSpec


def _resolve_data_path(value: str | None) -> str | None:
    """Resolve a data file as given, else relative to the repository root.

    A spec submitted as a YAML *string* (over the API) has no file to anchor relative paths to,
    so a path like `backend/data/x.csv` would otherwise miss depending on the server's working
    directory. Missing files raise here rather than degrading silently.
    """
    if not value:
        return value
    given = Path(value)
    if given.exists():
        return str(given)
    repo_root = Path(__file__).resolve().parents[2]     # backend/workflow/runner.py -> repo root
    candidate = repo_root / value
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(f"data file not found: '{value}' (also tried '{candidate}')")


def build_engine(data: DataSpec, db_path: str | None = None):
    """Seed the store from the spec's data source and return a loaded engine.

    Refuses to run on anything other than the requested source: the seeder falls back to
    synthetic data when a real source fails, which is right for booting a demo but wrong for a
    reproducible analysis — the same spec would silently yield different numbers.
    """
    from analytics.engine import MacroShockEngine  # noqa: PLC0415 - keep import cost lazy
    from data import seed as seed_mod  # noqa: PLC0415

    db = db_path or os.path.join(tempfile.gettempdir(), "macroshock_workflow.db")
    seed_mod.seed(
        db_path=db,
        source=data.source,
        csv_path=_resolve_data_path(data.asset_returns),
        factors_csv=_resolve_data_path(data.factor_returns),
        start=data.start or "2010-01-01",
    )
    engine = MacroShockEngine(db)

    actual = str(engine.dataset_meta.get("source", "unknown"))
    if not actual.startswith(data.source):
        raise ValueError(
            f"requested data source '{data.source}' but the loaded dataset reports '{actual}'. "
            "Refusing to continue: a silent fallback would produce different numbers for the "
            "same specification."
        )
    return engine


def _require(params: dict[str, Any], key: str, step: str) -> Any:
    if key not in params:
        raise ValueError(f"step '{step}' (run: needs '{key}') is missing parameter '{key}'.")
    return params[key]


# ---------------------------------------------------------------- step handlers
def _meta(engine, w, p, name):            return engine.meta()
def _exposures(engine, w, p, name):       return engine.exposure_report()
def _risk(engine, w, p, name):            return engine.risk_report(w)
def _backtest(engine, w, p, name):        return engine.backtest()


def _regression(engine, w, p, name):
    return engine.factor_regression(w, ridge_lambda=float(p.get("ridge_lambda", 0.0)))


def _stress(engine, w, p, name):
    return engine.stress_test(w, _require(p, "scenario_id", name),
                              float(p.get("confidence", 0.95)))


def _custom_stress(engine, w, p, name):
    return engine.custom_stress_test(w, _require(p, "shocks", name),
                                     p.get("name", "Custom scenario"),
                                     float(p.get("confidence", 0.95)))


def _active_risk(engine, w, p, name):
    bench = p.get("benchmark_weights") or p.get("benchmark") or p.get("benchmark_id") or "US 60/40"
    return engine.active_risk(w, bench)


def _reverse(engine, w, p, name):
    return engine.reverse_stress(w, float(p.get("target_loss", 0.20)))


STEP_HANDLERS: dict[str, Callable] = {
    "meta": _meta,
    "exposures": _exposures,
    "risk-contribution": _risk,
    "factor-regression": _regression,
    "stress-test": _stress,
    "custom-stress-test": _custom_stress,
    "active-risk": _active_risk,
    "reverse-stress": _reverse,
    "backtest": _backtest,
}


def _step_params(spec: MacroShockSpec, step: StepSpec) -> dict[str, Any]:
    """Global parameters, overridden by the step's own `with:` block."""
    params = dict(spec.inputs.parameters)
    params.update(step.with_)
    return params


def _spec_digest(spec: MacroShockSpec) -> str:
    """Stable digest of the validated spec — two identical specs produce the same run id."""
    canonical = spec.model_dump_json(by_alias=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def run_workflow(spec: MacroShockSpec, output_dir: str | Path | None = None,
                 engine=None) -> dict:
    """Run every step in order, write artifacts, and return the run summary."""
    out = Path(output_dir or spec.outputs.directory)
    out.mkdir(parents=True, exist_ok=True)

    engine = engine or build_engine(spec.inputs.data)
    weights = spec.inputs.portfolio

    unknown = set(weights) - set(engine.tickers)
    if unknown:
        raise ValueError(f"inputs.portfolio has unknown ticker(s) {sorted(unknown)}; "
                         f"valid tickers: {engine.tickers}")

    started = time.perf_counter()
    steps_report: list[dict] = []
    for step in spec.workflow.steps:
        handler = STEP_HANDLERS[step.run]
        t0 = time.perf_counter()
        result = handler(engine, weights, _step_params(spec, step), step.name)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        artifact = out / f"{step.name}.json"
        artifact.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
        steps_report.append({"name": step.name, "run": step.run,
                             "duration_ms": elapsed_ms, "artifact": artifact.name})

    summary = {
        "workflow": spec.metadata.get("name", "macroshock-workflow"),
        "spec_version": spec.version,
        "spec_digest": _spec_digest(spec),
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total_duration_ms": round((time.perf_counter() - started) * 1000, 2),
        # Provenance: everything needed to reproduce these numbers.
        "model_version": engine.model_version,
        "dataset": engine.dataset_meta,
        "portfolio": weights,
        "steps": steps_report,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float),
                                      encoding="utf-8")
    return summary
