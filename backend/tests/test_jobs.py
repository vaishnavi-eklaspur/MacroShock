"""Tests for asynchronous workflow submission.

These exercise the **inline fallback** (no broker present, as in CI): submission must still work
end-to-end and must say plainly that it ran in-process rather than claiming to be queued. The
queued path shares the same interface; what is asserted here is the contract every caller sees.
"""
import pytest

from app import create_app

SPEC = {
    "version": "1.0",
    "metadata": {"name": "job-test"},
    "inputs": {
        "data": {"source": "synthetic"},
        "portfolio": {"SPY": 0.6, "IEF": 0.4},
    },
    "workflow": {
        "type": "serial",
        "steps": [{"name": "risk", "run": "risk-contribution"}],
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Force the in-process path and keep artifacts out of the repo.
    monkeypatch.setenv("MACROSHOCK_DISABLE_CELERY", "1")
    monkeypatch.setenv("MACROSHOCK_RESULTS_DIR", str(tmp_path / "results"))
    return create_app().test_client()


def test_health_reports_the_job_queue_mode(client):
    body = client.get("/health").get_json()
    assert body["job_queue"] == "inline"


def test_submit_returns_202_and_a_job_record(client):
    r = client.post("/api/workflows", json={"spec": SPEC})
    assert r.status_code == 202
    job = r.get_json()
    assert job["job_id"]
    # Honest about execution mode rather than pretending it was queued.
    assert job["mode"] == "inline"
    assert job["status"] == "SUCCESS"
    assert job["result"]["model_version"]
    assert [s["name"] for s in job["result"]["steps"]] == ["risk"]


def test_submit_accepts_a_raw_yaml_spec(client):
    import yaml
    r = client.post("/api/workflows", json={"spec_yaml": yaml.safe_dump(SPEC)})
    assert r.status_code == 202
    assert r.get_json()["status"] == "SUCCESS"


def test_status_round_trip(client):
    job_id = client.post("/api/workflows", json={"spec": SPEC}).get_json()["job_id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.get_json()["job_id"] == job_id


def test_unknown_job_id_is_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_invalid_spec_is_rejected_before_execution(client):
    bad = {"version": "1.0", "inputs": {"portfolio": {}},
           "workflow": {"steps": [{"name": "x", "run": "risk-contribution"}]}}
    r = client.post("/api/workflows", json={"spec": bad})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_missing_spec_is_rejected(client):
    assert client.post("/api/workflows", json={}).status_code == 400
