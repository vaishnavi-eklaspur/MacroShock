"""Tests for optional real-time job notifications.

The property that matters is containment: when the feature is off (the default) nothing about the
API changes, and when it is on a failed notification can never fail the job that produced it.
Polling stays the reliable path either way.
"""
import pytest

import realtime
from app import create_app


@pytest.fixture(autouse=True)
def _reset_module_state():
    # init_realtime caches a server on the module; keep tests independent of each other.
    realtime._socketio = None
    yield
    realtime._socketio = None


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MACROSHOCK_ENABLE_REALTIME", raising=False)
    assert realtime.realtime_enabled() is False
    assert realtime.init_realtime(create_app()) is None
    # Emitting is a no-op rather than an error.
    assert realtime.emit_job_event("job-1", "job_completed", {"x": 1}) is False


def test_health_reports_realtime_off_by_default(monkeypatch):
    monkeypatch.delenv("MACROSHOCK_ENABLE_REALTIME", raising=False)
    assert create_app().test_client().get("/health").get_json()["realtime"] is False


def test_enabled_attaches_a_server_and_emits(monkeypatch):
    pytest.importorskip("flask_socketio")
    monkeypatch.setenv("MACROSHOCK_ENABLE_REALTIME", "1")
    # No message queue: keep it in-process so the test needs no Redis.
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    app = create_app()
    assert realtime.realtime_enabled() is True
    assert realtime._socketio is not None, "expected a Socket.IO server to be attached"
    assert app.test_client().get("/health").get_json()["realtime"] is True

    emitted = {}
    monkeypatch.setattr(realtime._socketio, "emit",
                        lambda event, payload, room=None: emitted.update(
                            event=event, payload=payload, room=room))
    assert realtime.emit_job_event("job-42", "job_completed", {"status": "SUCCESS"}) is True
    assert emitted == {"event": "job_completed", "payload": {"status": "SUCCESS"},
                       "room": "job-42"}


def test_emit_failure_is_swallowed(monkeypatch):
    pytest.importorskip("flask_socketio")
    monkeypatch.setenv("MACROSHOCK_ENABLE_REALTIME", "1")

    class Exploding:
        def emit(self, *a, **k):
            raise RuntimeError("socket layer down")

    realtime._socketio = Exploding()
    # A missed notification must not propagate into the job that produced it.
    assert realtime.emit_job_event("job-7", "job_completed", {}) is False


def test_submitting_a_job_still_works_with_realtime_enabled(monkeypatch, tmp_path):
    pytest.importorskip("flask_socketio")
    monkeypatch.setenv("MACROSHOCK_ENABLE_REALTIME", "1")
    monkeypatch.setenv("MACROSHOCK_DISABLE_CELERY", "1")
    monkeypatch.setenv("MACROSHOCK_RESULTS_DIR", str(tmp_path))
    spec = {
        "version": "1.0",
        "inputs": {"data": {"source": "synthetic"}, "portfolio": {"SPY": 1.0}},
        "workflow": {"steps": [{"name": "risk", "run": "risk-contribution"}]},
    }
    r = create_app().test_client().post("/api/workflows", json={"spec": spec})
    assert r.status_code == 202
    assert r.get_json()["status"] == "SUCCESS"
