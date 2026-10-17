"""Kernel settings, read from the environment (``AOS_*``). Defaults suit ``make dev`` on a laptop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DEV_SECRET = "aos-dev-session-secret-change-me-0123456789abcdef"


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://aos_kernel:aos_kernel_dev@127.0.0.1:5432/aos"
    session_secret: str = DEV_SECRET
    org_file: Path = REPO / "seed" / "org.yaml"
    packs_dir: Path = REPO / "packs"
    seed_on_start: bool = True
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    pool_max: int = 10
    web_dist: Path | None = None   # serve the built React app from the API origin when set
    eval_strict: bool = False      # when true, deferred eval expectations block approve/activate
    sse_heartbeat_seconds: float = 15.0
    worker_lease_seconds: float = 90.0
    scheduler_interval_seconds: float = 5.0


    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        env = os.environ
        values = {
            "database_url": env.get("AOS_DATABASE_URL", cls.database_url),
            "session_secret": env.get("AOS_SESSION_SECRET", cls.session_secret),
            "org_file": Path(env.get("AOS_ORG_FILE", str(cls.org_file))),
            "packs_dir": Path(env.get("AOS_PACKS_DIR", str(cls.packs_dir))),
            "seed_on_start": env.get("AOS_SEED_ON_START", "1") not in ("0", "false", "no"),
            "cors_origins": [o for o in env.get("AOS_CORS_ORIGINS", "http://localhost:5173").split(",") if o],
            "web_dist": Path(env["AOS_WEB_DIST"]) if env.get("AOS_WEB_DIST") else None,
            "eval_strict": env.get("AOS_EVAL_STRICT", "0") in ("1", "true", "yes"),
            "sse_heartbeat_seconds": float(env.get("AOS_SSE_HEARTBEAT_SECONDS", "15")),
            "worker_lease_seconds": float(env.get("AOS_WORKER_LEASE_SECONDS", "90")),
            "scheduler_interval_seconds": float(env.get("AOS_SCHEDULER_INTERVAL_SECONDS", "5")),
        }
        values.update(overrides)
        return cls(**values)
