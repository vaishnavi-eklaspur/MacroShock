"""Celery task definitions for long-running analyses.

A full workflow (regime fit + multi-scenario stress + bootstrap CIs + backtest) is a compute job,
not something to hold an HTTP connection open for. The API enqueues it and returns a job id;
a worker process executes it and stores the result.

The broker is Redis (already a dependency). If no broker is reachable the job layer degrades to
in-process execution — the same philosophy as the cache: the service must not fail because an
optional piece of infrastructure is missing.
"""
from __future__ import annotations

import os

from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", BROKER_URL)

celery_app = Celery("macroshock", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,          # so a client can distinguish queued from running
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    worker_max_tasks_per_child=50,    # numpy/scipy workloads: recycle to bound memory growth
)


@celery_app.task(name="macroshock.run_workflow", bind=True)
def run_workflow_task(self, spec_dict: dict, output_dir: str | None = None) -> dict:
    """Execute a validated workflow specification and return its provenance-stamped summary."""
    from workflow.runner import run_workflow  # noqa: PLC0415 - keep worker import cost lazy
    from workflow.spec import MacroShockSpec  # noqa: PLC0415

    from realtime import emit_job_event  # noqa: PLC0415

    spec = MacroShockSpec(**spec_dict)
    summary = run_workflow(spec, output_dir=output_dir)
    # Published through the Redis message queue so the API process relays it to subscribers.
    emit_job_event(self.request.id, "job_completed",
                   {"job_id": self.request.id, "status": "SUCCESS", "result": summary})
    return summary
