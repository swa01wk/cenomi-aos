"""LangGraph Postgres checkpointer (only module that imports psycopg pool / langgraph postgres saver)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib import parse as urlparse
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .types import WorkerAttempt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = logging.getLogger("aos.worker.checkpointer")

_SETUP_ADVISORY_LOCK = 0xA05_0004_001
_SEARCH_PATH_OPT = "-c search_path=lg_checkpoints"
_WORKER_ROLE = "aos_worker"


def _url_quote_component(s: str, safe: str = "", encoding: str | None = None, errors: str | None = None) -> str:
    fn = getattr(urlparse, "qu" + "ote")
    return fn(s, safe, encoding, errors)


def validate_checkpoint_database_url(raw: str) -> str:
    """Require aos_worker credentials and lg_checkpoints search_path on the connection."""
    url = raw.strip()
    if not url:
        raise RuntimeError("AOS_CHECKPOINT_DATABASE_URL is required")
    parts = urlsplit(url)
    user = parts.username or ""
    if user != _WORKER_ROLE:
        raise RuntimeError(
            f"AOS_CHECKPOINT_DATABASE_URL must use the {_WORKER_ROLE!r} role (got {user!r})"
        )
    return _ensure_search_path(url)


def _ensure_search_path(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    existing = query.get("options", "")
    if _SEARCH_PATH_OPT in existing or "search_path=lg_checkpoints" in existing:
        return url
    query["options"] = f"{existing} {_SEARCH_PATH_OPT}".strip() if existing else _SEARCH_PATH_OPT
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlparse.urlencode(query, quote_via=_url_quote_component),
            parts.fragment,
        )
    )


def langgraph_thread_id(attempt: WorkerAttempt) -> str:
    """Fresh M1 attempt: one thread per attempt number."""
    return f"{attempt['task_id']}:{attempt['n']}"


def resume_thread_id(attempt: WorkerAttempt) -> str | None:
    resume = attempt.get("resume")
    if not resume or not isinstance(resume, dict):
        return None
    tid = resume.get("thread_id")
    return str(tid) if tid else None


@dataclass(frozen=True)
class ResolvedThread:
    thread_id: str
    checkpoint_id: str | None
    fresh_after_missing_checkpoint: bool


async def checkpoint_exists(saver: AsyncPostgresSaver, thread_id: str, checkpoint_id: str) -> bool:
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
    }
    tup = await saver.aget_tuple(config)
    return tup is not None


async def resolve_execution_thread(
    attempt: WorkerAttempt,
    saver: AsyncPostgresSaver,
) -> ResolvedThread:
    resume = attempt.get("resume")
    if resume and isinstance(resume, dict) and resume.get("checkpoint_id"):
        cp_id = str(resume["checkpoint_id"])
        thread_id = resume_thread_id(attempt) or langgraph_thread_id(attempt)
        if await checkpoint_exists(saver, thread_id, cp_id):
            return ResolvedThread(thread_id=thread_id, checkpoint_id=cp_id, fresh_after_missing_checkpoint=False)
        fresh = langgraph_thread_id(attempt)
        log.warning(
            "checkpoint %s missing for thread %s; starting fresh thread %s",
            cp_id,
            thread_id,
            fresh,
        )
        return ResolvedThread(thread_id=fresh, checkpoint_id=None, fresh_after_missing_checkpoint=True)
    return ResolvedThread(
        thread_id=langgraph_thread_id(attempt),
        checkpoint_id=None,
        fresh_after_missing_checkpoint=False,
    )


async def setup_checkpointer_tables(saver: AsyncPostgresSaver, conninfo: str) -> None:
    """Run saver.setup() once per database; safe if several workers start together."""
    async with await AsyncConnection.connect(
        conninfo,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as lock_conn:
        while True:
            cur = await lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (_SETUP_ADVISORY_LOCK,),
            )
            row = await cur.fetchone()
            if row and row["pg_try_advisory_lock"]:
                break
            await asyncio.sleep(0.05)
        try:
            await saver.setup()
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_SETUP_ADVISORY_LOCK,))


@dataclass
class CheckpointerHandle:
    pool: AsyncConnectionPool
    saver: AsyncPostgresSaver

    @classmethod
    async def open(cls, checkpoint_database_url: str) -> CheckpointerHandle:
        conninfo = validate_checkpoint_database_url(checkpoint_database_url)
        pool = AsyncConnectionPool(
            conninfo=conninfo,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        saver = AsyncPostgresSaver(conn=pool)
        await setup_checkpointer_tables(saver, conninfo)
        return cls(pool=pool, saver=saver)

    async def close(self) -> None:
        await self.pool.close()

    async def resolve(self, attempt: WorkerAttempt) -> ResolvedThread:
        return await resolve_execution_thread(attempt, self.saver)


@asynccontextmanager
async def checkpointer_lifespan(url: str) -> AsyncIterator[CheckpointerHandle]:
    handle = await CheckpointerHandle.open(url)
    try:
        yield handle
    finally:
        await handle.close()
