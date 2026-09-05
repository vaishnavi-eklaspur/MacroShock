"""Real-time job notifications over Socket.IO.

Polling `GET /api/jobs/<id>` is the reliable baseline and always works. This adds push: a client
subscribes to a job and is told the moment it finishes, instead of discovering it up to one poll
interval later.

Design notes:

* **Off by default** (`MACROSHOCK_ENABLE_REALTIME=1` to enable). Real-time transport changes the
  server model, and an optional convenience must never destabilise the compute API.
* **`threading` async mode by default** rather than eventlet/gevent, because monkey-patching the
  whole process to get a WebSocket upgrade is a poor trade against a numeric workload. Socket.IO
  negotiates the best available transport, falling back to HTTP long-polling; set
  `MACROSHOCK_SOCKETIO_ASYNC_MODE=eventlet` (with a matching gunicorn worker) for true WebSocket.
* **Redis message queue** when configured, so a Celery worker in another process can publish an
  event that the API process relays to connected clients.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("macroshock.realtime")

_socketio = None          # server instance, set by init_realtime in the API process


def realtime_enabled() -> bool:
    return os.getenv("MACROSHOCK_ENABLE_REALTIME") == "1"


def _message_queue() -> str | None:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") or None


def init_realtime(app):
    """Attach a Socket.IO server to the Flask app. Returns None when disabled/unavailable."""
    global _socketio
    if not realtime_enabled():
        return None
    try:
        from flask_socketio import SocketIO, join_room  # noqa: PLC0415 - optional dependency
    except ImportError:
        logger.warning("flask-socketio is not installed; real-time notifications disabled.")
        return None

    kwargs = {
        "async_mode": os.getenv("MACROSHOCK_SOCKETIO_ASYNC_MODE", "threading"),
        "cors_allowed_origins": os.getenv("CORS_ORIGINS", "*"),
        "logger": False,
        "engineio_logger": False,
    }
    queue = _message_queue()
    if queue:
        kwargs["message_queue"] = queue

    socketio = SocketIO(app, **kwargs)

    @socketio.on("subscribe")
    def _subscribe(data):
        """Join the room for a job so this client receives only that job's events."""
        job_id = (data or {}).get("job_id")
        if not job_id:
            return
        join_room(job_id)
        socketio.emit("subscribed", {"job_id": job_id}, room=job_id)

    _socketio = socketio
    logger.info("Real-time notifications enabled (async_mode=%s, message_queue=%s).",
                kwargs["async_mode"], bool(queue))
    return socketio


def emit_job_event(job_id: str, event: str, payload: dict) -> bool:
    """Publish a job event to subscribers. Returns True if it was published.

    Safe to call from anywhere, including a Celery worker with no Flask app: when there is no
    in-process server it publishes through the Redis message queue instead. Never raises — a
    missed notification must not fail the job that produced it.
    """
    if not realtime_enabled():
        return False
    try:
        if _socketio is not None:
            _socketio.emit(event, payload, room=job_id)
            return True

        queue = _message_queue()
        if not queue:
            return False
        from flask_socketio import SocketIO  # noqa: PLC0415

        # Client-only instance: publishes into the queue for the API process to relay.
        SocketIO(message_queue=queue).emit(event, payload, room=job_id)
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Failed to emit %s for job %s: %s", event, job_id, exc)
        return False
