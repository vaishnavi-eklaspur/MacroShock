"""Job submission and status, with graceful degradation.

Wraps the Celery queue so the API has one interface regardless of deployment:

* **Broker reachable** — the workflow is enqueued and a worker runs it; the client polls for
  status. This is the production path (and how CERN-style batch analysis actually works).
* **No broker** — the workflow runs in-process and the job is returned already completed, so a
  single-container demo still works. The response says which mode was used, so a caller is never
  misled about whether the work was truly asynchronous.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger("macroshock.jobs")

# Terminal + in-flight states, normalised across both execution modes.
PENDING, STARTED, SUCCESS, FAILURE = "PENDING", "STARTED", "SUCCESS", "FAILURE"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class JobQueue:
    """Submit workflow specs for execution and report their status."""

    def __init__(self, output_root: str | None = None):
        self.output_root = output_root or os.getenv("MACROSHOCK_RESULTS_DIR", "results")
        self._inline: dict[str, dict[str, Any]] = {}   # job_id -> job record (fallback mode)
        self._celery = None
        self._task = None

        if os.getenv("MACROSHOCK_DISABLE_CELERY") == "1":
            logger.info("Celery disabled by configuration; running jobs in-process.")
            return
        try:
            from tasks import celery_app, run_workflow_task  # noqa: PLC0415

            # Ping the broker: importing Celery never fails, so only a real round-trip tells us
            # whether a worker could actually pick the job up.
            conn = celery_app.connection()
            conn.ensure_connection(max_retries=0, timeout=1)
            conn.release()
            self._celery, self._task = celery_app, run_workflow_task
            logger.info("Celery broker reachable; jobs will be queued.")
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Celery broker unavailable (%s); jobs will run in-process.", exc)
            self._celery = None

    @property
    def enabled(self) -> bool:
        """True when jobs are genuinely queued to a worker."""
        return self._celery is not None

    # ------------------------------------------------------------------ submit
    def submit(self, spec) -> dict:
        """Enqueue (or inline-run) a validated spec. Returns a job record."""
        spec_dict = spec.model_dump(by_alias=True)
        job_id = str(uuid.uuid4())
        out_dir = os.path.join(self.output_root, job_id)

        if self.enabled:
            async_result = self._task.apply_async(args=[spec_dict, out_dir], task_id=job_id)
            return {"job_id": async_result.id, "status": PENDING, "mode": "queued",
                    "submitted_utc": _now()}

        # Fallback: execute now so a single-container deployment still works end-to-end.
        record = {"job_id": job_id, "mode": "inline", "submitted_utc": _now()}
        try:
            from workflow.runner import run_workflow  # noqa: PLC0415

            record.update(status=SUCCESS, result=run_workflow(spec, output_dir=out_dir))
        except Exception as exc:
            logger.exception("inline workflow failed")
            record.update(status=FAILURE, error=str(exc))
        record["completed_utc"] = _now()
        self._inline[job_id] = record
        # Push notification is best-effort; polling remains the reliable path.
        from realtime import emit_job_event  # noqa: PLC0415
        emit_job_event(job_id, "job_completed", record)
        return record

    # ------------------------------------------------------------------ status
    def status(self, job_id: str) -> dict | None:
        """Current job state, or None if the id is unknown."""
        if job_id in self._inline:
            return self._inline[job_id]
        if not self.enabled:
            return None

        res = self._celery.AsyncResult(job_id)
        # Celery reports PENDING for unknown ids too; that ambiguity is inherent, so say so
        # rather than pretending an unknown id is a queued job.
        state = res.state
        job: dict[str, Any] = {"job_id": job_id, "status": state, "mode": "queued"}
        if state == SUCCESS:
            job["result"] = res.result
        elif state == FAILURE:
            job["error"] = str(res.result)
        elif state == PENDING:
            job["note"] = "queued, or an unknown job id (Celery cannot distinguish the two)"
        return job
