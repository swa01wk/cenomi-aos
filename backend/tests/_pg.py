"""Scratch Postgres databases for tests: create, migrate as the owner, drop. Skips cleanly without Postgres."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _admin_env(url: str) -> dict[str, str]:
    """libpq environment for a superuser URL, so psql, createdb and dropdb all reach the same server."""
    u = urlsplit(url)
    env = dict(os.environ)
    env.update({k: v for k, v in {"PGHOST": u.hostname, "PGPORT": str(u.port or 5432), "PGUSER": unquote(u.username or ""),
                                  "PGPASSWORD": unquote(u.password or ""), "PGDATABASE": u.path.lstrip("/") or "postgres"}.items() if v})
    return env


def _admin(cmd: str, **kw) -> subprocess.CompletedProcess:
    # Local dev cluster: the postgres OS user. In CI (or Docker) set AOS_TEST_ADMIN_URL to a superuser URL instead,
    # e.g. postgresql://postgres:postgres@localhost:5432/postgres
    url = os.environ.get("AOS_TEST_ADMIN_URL")
    if url:
        return subprocess.run(["bash", "-c", cmd], env=_admin_env(url), **kw)
    return subprocess.run(["su", "postgres", "-c", cmd], **kw)


def available() -> bool:
    ok = False
    if shutil.which("psql"):
        try:
            _admin("psql -Atc 'select 1'", check=True, capture_output=True, timeout=10)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
    if not ok and os.environ.get("AOS_TEST_REQUIRE_PG") == "1":
        # CI and .env set this so database tests fail loudly instead of being skipped.
        raise RuntimeError("AOS_TEST_REQUIRE_PG=1 but Postgres is not reachable: run `make db` and set AOS_TEST_ADMIN_URL")
    return ok


def create_migrated() -> str:
    db = "aos_t_" + uuid.uuid4().hex[:8]
    _admin(f"createdb {db}", check=True)
    files = " ".join(f"-f {p}" for p in sorted(MIGRATIONS.glob("*.sql")))
    _admin(f"psql -q -v ON_ERROR_STOP=1 -d {db} {files}", check=True, capture_output=True)
    return db


def drop(db: str) -> None:
    _admin(f"dropdb --if-exists --force {db}", check=False, capture_output=True)


def admin_sql(db: str, sql: str, check: bool = True) -> subprocess.CompletedProcess:
    return _admin(f"psql -q -v ON_ERROR_STOP=1 -At -d {db}", input=sql, text=True, capture_output=True, check=check)


def kernel_url(db: str) -> str:
    url = os.environ.get("AOS_TEST_ADMIN_URL")
    host, port = ("127.0.0.1", 5432)
    if url:
        u = urlsplit(url)
        host, port = u.hostname or host, u.port or port
    return f"postgresql://aos_kernel:aos_kernel_dev@{host}:{port}/{db}"


def role_url(db: str, role: str, *, search_path_lg: bool = False) -> str:
    url = os.environ.get("AOS_TEST_ADMIN_URL")
    host, port = ("127.0.0.1", 5432)
    if url:
        u = urlsplit(url)
        host, port = u.hostname or host, u.port or port
    base = f"postgresql://{role}:{role}_dev@{host}:{port}/{db}"
    if search_path_lg:
        return base + "?options=-c%20search_path%3Dlg_checkpoints"
    return base


def worker_checkpoint_url(db: str) -> str:
    url = os.environ.get("AOS_TEST_ADMIN_URL")
    host, port = ("127.0.0.1", 5432)
    if url:
        u = urlsplit(url)
        host, port = u.hostname or host, u.port or port
    return role_url(db, "aos_worker", search_path_lg=True)


def require_runtime_extra() -> None:
    try:
        import langgraph.checkpoint.postgres.aio  # noqa: F401
    except ImportError as exc:
        if os.environ.get("AOS_TEST_REQUIRE_PG") == "1":
            raise RuntimeError(
                "AOS_TEST_REQUIRE_PG=1 but backend[runtime] is not installed "
                "(pip install -e 'backend[dev,runtime]')"
            ) from exc
        raise unittest.SkipTest("backend[runtime] not installed") from exc
