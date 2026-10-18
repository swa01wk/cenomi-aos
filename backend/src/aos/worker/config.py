"""Worker process configuration from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt

WORKER_AUD = "aos-worker"
_ALLOWED_LANES = frozenset({"assist", "task"})


@dataclass(frozen=True)
class WorkerConfig:
    api_url: str
    worker_token: str
    worker_id: str
    lanes: tuple[str, ...]
    runtime: str
    checkpoint_database_url: str
    poll_min_s: float
    poll_max_s: float
    submit_shutdown_timeout_s: float

    def __repr__(self) -> str:
        return (
            f"WorkerConfig(api_url={self.api_url!r}, worker_id={self.worker_id!r}, "
            f"lanes={self.lanes!r}, runtime={self.runtime!r}, worker_token=<redacted>)"
        )


def _worker_id_from_token(token: str) -> str:
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise RuntimeError("AOS_WORKER_TOKEN is invalid") from exc
    if claims.get("aud") != WORKER_AUD:
        raise RuntimeError("AOS_WORKER_TOKEN must have aud aos-worker")
    sub = claims.get("sub")
    if not sub:
        raise RuntimeError("AOS_WORKER_TOKEN must carry sub (worker id)")
    return str(sub)


def load_config() -> WorkerConfig:
    api_url = os.environ.get("AOS_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
    token = os.environ.get("AOS_WORKER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AOS_WORKER_TOKEN is required")

    worker_id = _worker_id_from_token(token)

    lanes_raw = os.environ.get("AOS_WORKER_LANES", "assist,task")
    lanes = tuple(x.strip() for x in lanes_raw.split(",") if x.strip())
    if not lanes:
        raise RuntimeError("AOS_WORKER_LANES must list at least one lane")
    unknown = [lane for lane in lanes if lane not in _ALLOWED_LANES]
    if unknown:
        raise RuntimeError(f"AOS_WORKER_LANES unknown lane(s): {', '.join(unknown)}")

    runtime = os.environ.get("AOS_RUNTIME", "").strip().lower()
    if not runtime:
        raise RuntimeError("AOS_RUNTIME is required (set to fake or langgraph)")
    if runtime == "langgraph":
        from .models import validate_real_model_startup

        validate_real_model_startup()

    from .checkpointer import validate_checkpoint_database_url

    checkpoint_url = os.environ.get("AOS_CHECKPOINT_DATABASE_URL", "").strip()
    checkpoint_database_url = validate_checkpoint_database_url(checkpoint_url)

    poll_min = float(os.environ.get("AOS_WORKER_POLL_MIN_S", "1"))
    poll_max = float(os.environ.get("AOS_WORKER_POLL_MAX_S", "5"))
    submit_timeout = float(os.environ.get("AOS_WORKER_SUBMIT_SHUTDOWN_TIMEOUT_S", "30"))

    return WorkerConfig(
        api_url=api_url,
        worker_token=token,
        worker_id=worker_id,
        lanes=lanes,
        runtime=runtime,
        checkpoint_database_url=checkpoint_database_url,
        poll_min_s=poll_min,
        poll_max_s=poll_max,
        submit_shutdown_timeout_s=submit_timeout,
    )
