"""Tests for object-store publication of run artifacts.

No MinIO is required: what matters is the contract — the store disables itself cleanly when
nothing is configured, publication never turns a successful computation into a failure, and when
a store *is* present its records reach the caller.
"""
import json

import pytest
import yaml

from artifacts import ArtifactStore
from workflow import load_spec, run_workflow
from workflow.runner import build_engine

SPEC = {
    "version": "1.0",
    "metadata": {"name": "artifact-test"},
    "inputs": {"data": {"source": "synthetic"}, "portfolio": {"SPY": 0.6, "IEF": 0.4}},
    "workflow": {"type": "serial", "steps": [{"name": "risk", "run": "risk-contribution"}]},
}


@pytest.fixture(scope="module")
def engine():
    from workflow.spec import DataSpec
    return build_engine(DataSpec(source="synthetic"))


def _spec_file(tmp_path):
    p = tmp_path / "macroshock.yaml"
    p.write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    return load_spec(p)


class FakeStore:
    """Stands in for S3 so the integration is testable without infrastructure."""

    enabled = True

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    def publish_directory(self, local_dir, prefix):
        from pathlib import Path
        self.calls.append(prefix)
        if self.fail:
            raise RuntimeError("object store exploded")
        return [
            {"key": f"{prefix}/{p.name}", "url": f"https://example.invalid/{p.name}",
             "size_bytes": p.stat().st_size, "expires_in_seconds": 3600}
            for p in sorted(Path(local_dir).glob("*.json"))
        ]


def test_store_disables_itself_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MACROSHOCK_S3_ENDPOINT", raising=False)
    store = ArtifactStore()
    assert store.enabled is False
    # A disabled store is still safe to call.
    assert store.publish_directory(".", "runs/x") == []


def test_run_without_a_store_still_produces_local_artifacts(tmp_path, engine, monkeypatch):
    monkeypatch.delenv("MACROSHOCK_S3_ENDPOINT", raising=False)
    out = tmp_path / "results"
    summary = run_workflow(_spec_file(tmp_path), output_dir=out, engine=engine)
    assert (out / "summary.json").exists()
    assert "artifacts" not in summary          # nothing published, and nothing pretended


def test_artifacts_are_published_and_urls_returned(tmp_path, engine):
    out = tmp_path / "results"
    store = FakeStore()
    summary = run_workflow(_spec_file(tmp_path), output_dir=out, engine=engine,
                           artifact_store=store)

    assert summary["artifact_prefix"].startswith("runs/")
    names = {a["key"].rsplit("/", 1)[-1] for a in summary["artifacts"]}
    # Step artifacts *and* the provenance summary are published.
    assert {"risk.json", "summary.json"} <= names
    assert all(a["url"].startswith("https://") for a in summary["artifacts"])


def test_summary_json_on_disk_records_provenance(tmp_path, engine):
    out = tmp_path / "results"
    run_workflow(_spec_file(tmp_path), output_dir=out, engine=engine, artifact_store=FakeStore())
    stored = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert stored["model_version"] and stored["spec_digest"]


def test_publication_failure_does_not_fail_the_run(tmp_path, engine):
    # The numbers are computed and on disk; a broken object store must not invalidate them.
    out = tmp_path / "results"
    summary = run_workflow(_spec_file(tmp_path), output_dir=out, engine=engine,
                           artifact_store=FakeStore(fail=True))
    assert summary["model_version"]                 # the run still succeeded
    assert "object store exploded" in summary["artifact_error"]
    assert (out / "summary.json").exists()
