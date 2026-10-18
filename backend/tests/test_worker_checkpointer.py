"""AsyncPostgresSaver on lg_checkpoints as aos_worker; thread_id rules."""

from __future__ import annotations

import asyncio
import operator
import subprocess
import unittest
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, MagicMock

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from aos.worker.checkpointer import (
    CheckpointerHandle,
    _ensure_search_path,
    langgraph_thread_id,
    resolve_execution_thread,
    setup_checkpointer_tables,
    validate_checkpoint_database_url,
)
from aos.worker.default_fake import minimal_agent_result
from aos.worker.runtime import ScriptedRuntime
from aos.worker.types import AgentResult, WorkerAttempt

from . import _pg


async def concurrent_setup_smoke(url: str, *, workers: int = 2) -> None:
    conninfo = validate_checkpoint_database_url(url)

    async def _one() -> None:
        pool = AsyncConnectionPool(
            conninfo=conninfo,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        saver = AsyncPostgresSaver(conn=pool)
        try:
            await setup_checkpointer_tables(saver, conninfo)
        finally:
            await pool.close()

    await asyncio.gather(*[_one() for _ in range(workers)])


class EnsureSearchPathTests(unittest.TestCase):
    def test_ensure_search_path_uses_percent_encoding_not_plus(self) -> None:
        plain = "postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos"
        out = _ensure_search_path(plain)
        self.assertIn("%20", out)
        self.assertNotIn("+search_path", out)

    def test_ensure_search_path_keeps_other_params_and_existing_option(self) -> None:
        base = "postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos"
        self.assertEqual(
            _ensure_search_path(base + "?sslmode=disable"),
            base + "?sslmode=disable&options=-c%20search_path%3Dlg_checkpoints",
        )
        already = base + "?options=-c%20search_path%3Dlg_checkpoints"
        self.assertEqual(_ensure_search_path(already), already)

    def test_ensure_search_path_refuses_other_options(self) -> None:
        url = "postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos?options=-c%20statement_timeout%3D5000"
        with self.assertRaisesRegex(RuntimeError, "search_path=lg_checkpoints"):
            _ensure_search_path(url)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerCheckpointerTests(unittest.TestCase):
    db: str

    @classmethod
    def setUpClass(cls) -> None:
        _pg.require_runtime_extra()
        cls.db = _pg.create_migrated()

    @classmethod
    def tearDownClass(cls) -> None:
        _pg.drop(cls.db)

    def _worker_url(self) -> str:
        return _pg.worker_checkpoint_url(self.db)

    def _plain_worker_url(self) -> str:
        return _pg.role_url(self.db, "aos_worker")

    def test_open_plain_url_sets_search_path_and_lg_checkpoints_tables(self) -> None:
        async def _run() -> None:
            handle = await CheckpointerHandle.open(self._plain_worker_url())
            try:
                async with handle.pool.connection() as conn:
                    cur = await conn.execute("show search_path")
                    row = await cur.fetchone()
                    self.assertEqual(row["search_path"], "lg_checkpoints")
                in_lg = _pg.admin_sql(
                    self.db,
                    "select count(*) from information_schema.tables"
                    " where table_schema = 'lg_checkpoints'"
                    " and table_name like 'checkpoint%';",
                ).stdout.strip()
                in_public = _pg.admin_sql(
                    self.db,
                    "select count(*) from information_schema.tables"
                    " where table_schema = 'public'"
                    " and table_name like 'checkpoint%';",
                ).stdout.strip()
                self.assertGreater(int(in_lg), 0)
                self.assertEqual(int(in_public), 0)
            finally:
                await handle.close()

        asyncio.run(_run())

    def test_setup_creates_tables_in_lg_checkpoints_not_public(self) -> None:
        async def _run() -> None:
            handle = await CheckpointerHandle.open(self._worker_url())
            try:
                in_lg = _pg.admin_sql(
                    self.db,
                    "select count(*) from information_schema.tables"
                    " where table_schema = 'lg_checkpoints'"
                    " and table_name like 'checkpoint%';",
                ).stdout.strip()
                in_public = _pg.admin_sql(
                    self.db,
                    "select count(*) from information_schema.tables"
                    " where table_schema = 'public'"
                    " and table_name like 'checkpoint%';",
                ).stdout.strip()
                self.assertGreater(int(in_lg), 0)
                self.assertEqual(int(in_public), 0)
            finally:
                await handle.close()

        asyncio.run(_run())

    def test_concurrent_setup_succeeds(self) -> None:
        asyncio.run(concurrent_setup_smoke(self._worker_url(), workers=2))

    def test_aos_worker_denied_on_business_schemas(self) -> None:
        url = _pg.role_url(self.db, "aos_worker")
        for sql in (
            "select 1 from org.people limit 1;",
            "select 1 from work.tasks limit 1;",
            "select 1 from evidence.audit_events limit 1;",
        ):
            proc = subprocess.run(
                ["psql", url, "-q", "-v", "ON_ERROR_STOP=1", "-At"],
                input=sql,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("permission denied", proc.stderr.lower())

    def test_save_then_resume_same_thread_retry_new_thread(self) -> None:
        from langgraph.graph import END, START, StateGraph

        class St(TypedDict):
            count: Annotated[int, operator.add]

        async def bump(state: St) -> dict[str, int]:
            # First superstep adds 1; resume merges input only (no second +1 from this node).
            if state.get("count", 0) >= 1:
                return {"count": 0}
            return {"count": 1}

        async def _run() -> None:
            conninfo = validate_checkpoint_database_url(self._worker_url())
            pool = AsyncConnectionPool(
                conninfo=conninfo,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            await pool.open()
            saver = AsyncPostgresSaver(conn=pool)
            await setup_checkpointer_tables(saver, conninfo)
            graph = StateGraph(St)
            graph.add_node("bump", bump)
            graph.add_edge(START, "bump")
            graph.add_edge("bump", END)
            compiled = graph.compile(checkpointer=saver)

            task_id = "task_cp_test"
            t1 = f"{task_id}:1"
            config1 = {"configurable": {"thread_id": t1}}
            out1 = await compiled.ainvoke({"count": 0}, config1)
            self.assertEqual(out1["count"], 1)
            tup1 = await saver.aget_tuple(config1)
            self.assertIsNotNone(tup1)
            cp_id = tup1.config["configurable"]["checkpoint_id"]

            attempt_resume: WorkerAttempt = {
                "attempt_id": "att_2",
                "task_id": task_id,
                "instance_id": "inst",
                "n": 2,
                "fencing_token": 1,
                "lease_seconds": 90,
                "kind": "assist",
                "contract": {},
                "resume": {"thread_id": t1, "checkpoint_id": cp_id, "signal": {}},
            }
            resolved = await resolve_execution_thread(attempt_resume, saver)
            self.assertFalse(resolved.fresh_after_missing_checkpoint)
            resume_config = {
                "configurable": {
                    "thread_id": resolved.thread_id,
                    "checkpoint_id": resolved.checkpoint_id,
                },
            }
            out1b = await compiled.ainvoke({"count": 1}, resume_config)
            self.assertEqual(out1b["count"], 2)

            t2 = f"{task_id}:2"
            out2 = await compiled.ainvoke({"count": 0}, {"configurable": {"thread_id": t2}})
            self.assertEqual(out2["count"], 1)
            await pool.close()

        asyncio.run(_run())

    def test_missing_checkpoint_starts_fresh_thread_and_agent_started(self) -> None:
        async def _run() -> None:
            handle = await CheckpointerHandle.open(self._worker_url())
            try:
                attempt: WorkerAttempt = {
                    "attempt_id": "att_2",
                    "task_id": "task_x",
                    "instance_id": "inst_x",
                    "n": 2,
                    "fencing_token": 1,
                    "lease_seconds": 90,
                    "kind": "assist",
                    "contract": {
                        "schema_version": "aos.task_contract/1",
                        "contract_id": "c1",
                        "contract_hash": "a" * 64,
                        "dependency_versions": {},
                    },
                    "resume": {
                        "checkpoint_id": "00000000-0000-0000-0000-000000000099",
                        "thread_id": "task_x:1",
                        "signal": {},
                    },
                }
                resolved = await resolve_execution_thread(attempt, handle.saver)
                self.assertTrue(resolved.fresh_after_missing_checkpoint)
                self.assertEqual(resolved.thread_id, "task_x:2")

                posted: list[dict[str, Any]] = []

                async def capture_events(**kwargs: Any) -> None:
                    posted.extend(kwargs.get("events") or [])

                ctx = MagicMock()
                ctx.post_events = AsyncMock(side_effect=capture_events)
                ctx.assemble_context = AsyncMock(return_value={})
                ctx.check = MagicMock()

                async def finish(a: WorkerAttempt, c: object) -> AgentResult:
                    return minimal_agent_result(a)

                runtime = ScriptedRuntime([finish], checkpointer=handle)
                await runtime.resume(attempt, ctx)
                self.assertTrue(
                    any(
                        e.get("event_type") == "AgentStarted" and "Checkpoint missing" in e.get("redacted_summary", "")
                        for e in posted
                    ),
                    posted,
                )
                ctx.assemble_context.assert_any_call(reason="start")
            finally:
                await handle.close()

        asyncio.run(_run())

    def test_langgraph_thread_id_m1_fresh(self) -> None:
        attempt: WorkerAttempt = {
            "attempt_id": "a",
            "task_id": "task_1",
            "instance_id": "i",
            "n": 3,
            "fencing_token": 1,
            "lease_seconds": 90,
            "kind": "assist",
            "contract": {},
        }
        self.assertEqual(langgraph_thread_id(attempt), "task_1:3")


if __name__ == "__main__":
    unittest.main()
