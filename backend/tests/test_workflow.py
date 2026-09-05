"""Tests for the declarative workflow engine.

The contract that matters: a spec either validates and runs to completion producing provenance-
stamped artifacts, or it fails loudly before computing anything. Silent partial runs are the
failure mode a reproducible pipeline must not have.
"""
import json
import os

import pytest
import yaml

from workflow import load_spec, run_workflow
from workflow.runner import build_engine

VALID = {
    "version": "1.0",
    "metadata": {"name": "test-run"},
    "inputs": {
        "data": {"source": "synthetic"},
        "portfolio": {"SPY": 0.6, "IEF": 0.4},
        "parameters": {"confidence": 0.95},
    },
    "workflow": {
        "type": "serial",
        "steps": [
            {"name": "risk", "run": "risk-contribution"},
            {"name": "gfc", "run": "stress-test", "with": {"scenario_id": "GFC_2008"}},
        ],
    },
    "outputs": {"directory": "results"},
}


def _write(tmp_path, spec_dict, name="macroshock.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(spec_dict), encoding="utf-8")
    return p


# ---------------------------------------------------------------- validation
def test_valid_spec_parses(tmp_path):
    spec = load_spec(_write(tmp_path, VALID))
    assert spec.metadata["name"] == "test-run"
    assert [s.run for s in spec.workflow.steps] == ["risk-contribution", "stress-test"]
    # `with:` is exposed under the aliased field
    assert spec.workflow.steps[1].with_["scenario_id"] == "GFC_2008"


def test_unknown_step_is_rejected(tmp_path):
    bad = json.loads(json.dumps(VALID))
    bad["workflow"]["steps"][0]["run"] = "not-a-real-step"
    with pytest.raises(Exception):
        load_spec(_write(tmp_path, bad))


def test_typo_in_field_is_rejected_not_ignored(tmp_path):
    # extra="forbid": a misspelled key must fail rather than be silently dropped.
    bad = json.loads(json.dumps(VALID))
    bad["inputs"]["portfoliooo"] = bad["inputs"].pop("portfolio")
    with pytest.raises(Exception):
        load_spec(_write(tmp_path, bad))


def test_duplicate_step_names_rejected(tmp_path):
    bad = json.loads(json.dumps(VALID))
    bad["workflow"]["steps"][1]["name"] = bad["workflow"]["steps"][0]["name"]
    with pytest.raises(Exception):
        load_spec(_write(tmp_path, bad))


def test_negative_weight_rejected(tmp_path):
    bad = json.loads(json.dumps(VALID))
    bad["inputs"]["portfolio"]["SPY"] = -0.5
    with pytest.raises(Exception):
        load_spec(_write(tmp_path, bad))


def test_relative_data_path_resolves_against_the_spec_file(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "assets.csv").write_text("date,SPY\n2020-01-03,0.01\n", encoding="utf-8")
    s = json.loads(json.dumps(VALID))
    s["inputs"]["data"] = {"source": "csv", "asset_returns": "d/assets.csv"}
    spec = load_spec(_write(tmp_path, s))
    # Resolved to an absolute path next to the spec, so the run is CWD-independent.
    assert spec.inputs.data.asset_returns.endswith("assets.csv")
    assert "d" in spec.inputs.data.asset_returns


# ---------------------------------------------------------------- execution
@pytest.fixture(scope="module")
def engine():
    from workflow.spec import DataSpec
    return build_engine(DataSpec(source="synthetic"))


def test_run_writes_artifacts_and_provenance(tmp_path, engine):
    spec = load_spec(_write(tmp_path, VALID))
    out = tmp_path / "results"
    summary = run_workflow(spec, output_dir=out, engine=engine)

    # One artifact per step, plus the summary.
    assert (out / "risk.json").exists() and (out / "gfc.json").exists()
    assert (out / "summary.json").exists()

    # Provenance is what makes a result reproducible, so assert it is actually recorded.
    assert summary["model_version"]
    assert summary["dataset"]
    assert len(summary["spec_digest"]) == 16
    assert [s["name"] for s in summary["steps"]] == ["risk", "gfc"]

    # The stress step really computed something.
    gfc = json.loads((out / "gfc.json").read_text(encoding="utf-8"))
    assert gfc["portfolio_drawdown"] < 0


def test_same_spec_yields_same_digest(tmp_path, engine):
    a = run_workflow(load_spec(_write(tmp_path, VALID)), output_dir=tmp_path / "a", engine=engine)
    b = run_workflow(load_spec(_write(tmp_path, VALID)), output_dir=tmp_path / "b", engine=engine)
    assert a["spec_digest"] == b["spec_digest"]


def test_unknown_ticker_fails_before_computing(tmp_path, engine):
    bad = json.loads(json.dumps(VALID))
    bad["inputs"]["portfolio"] = {"NOTATICKER": 1.0}
    out = tmp_path / "never"
    with pytest.raises(ValueError, match="unknown ticker"):
        run_workflow(load_spec(_write(tmp_path, bad)), output_dir=out, engine=engine)
    # Fails loudly *before* writing any artifact.
    assert not list(out.glob("*.json"))


def test_missing_csv_fails_instead_of_falling_back_to_synthetic(tmp_path):
    # The seeder degrades to synthetic data when a real source fails — correct for booting a
    # demo, catastrophic for a reproducible analysis (same spec, different numbers, no error).
    from workflow.runner import build_engine
    from workflow.spec import DataSpec

    with pytest.raises((FileNotFoundError, ValueError)):
        build_engine(DataSpec(source="csv", asset_returns="nope/missing.csv"),
                     db_path=str(tmp_path / "x.db"))


def test_csv_path_resolves_relative_to_the_repository_root(tmp_path):
    # A spec submitted as a YAML string has no file to anchor relative paths to, so paths like
    # 'backend/data/...' must still resolve from the repo root.
    from workflow.runner import _resolve_data_path

    resolved = _resolve_data_path("backend/data/real_asset_returns.csv")
    assert resolved.endswith("real_asset_returns.csv")
    assert os.path.exists(resolved)


def test_missing_required_step_parameter_is_reported(tmp_path, engine):
    bad = json.loads(json.dumps(VALID))
    bad["workflow"]["steps"] = [{"name": "gfc", "run": "stress-test"}]   # no scenario_id
    with pytest.raises(ValueError, match="scenario_id"):
        run_workflow(load_spec(_write(tmp_path, bad)), output_dir=tmp_path / "x", engine=engine)
