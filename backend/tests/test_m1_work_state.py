"""M1-BE-01: M1 migration, ids, transactional outbox and execution events."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import unittest
from collections.abc import Callable
from datetime import timezone
from pathlib import Path

import jsonschema
import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from aos.api.problems import KernelProblem, register_problem_handlers
from aos.kernel import ids, outbox
from aos.kernel.org import load_org, seed_sql
from aos.kernel.outbox import ExecutionEventWrite, OutboxRow

from . import _pg

REPO = Path(__file__).resolve().parents[2]
ORG_FILE = REPO / "seed" / "org.yaml"
EXECUTION_EVENT_SCHEMA = json.loads(
    (REPO / "docs/specs/contracts/schemas/execution-event.schema.json").read_text()
)
PROBLEM_SCHEMA = json.loads((REPO / "docs/specs/contracts/schemas/problem.schema.json").read_text())

M1_TABLES = [
    "registry.seats",
    "registry.seat_events",
    "registry.seat_checks",
    "registry.eval_runs",
    "gov.decision_records",
    "gov.budget_ledger",
    "work.instances",
    "work.participants",
    "work.tasks",
    "work.attempts",
    "work.turns",
    "work.artifacts",
    "work.artifact_versions",
    "work.pending_items",
    "evidence.execution_events",
    "evidence.stream_heads",
    "evidence.outbox",
]

M1_UNIQUE_INDEXES = ["seats_one_live", "attempts_one_live"]

M1_CHECKS = [
    ("registry.seats", "activated_by <> configured_by"),
    ("gov.budget_ledger", "<= limit_usd"),
]


class IdTests(unittest.TestCase):
    def test_instance_prefix_validation(self) -> None:
        self.assertEqual(ids.format_instance_id("JX", 1), "JX-0001")
        self.assertEqual(ids.format_instance_id("ABCDE", 42), "ABCDE-0042")
        self.assertEqual(ids.format_instance_id("JX", 12345), "JX-12345")
        with self.assertRaises(ValueError):
            ids.format_instance_id("jx", 1)
        with self.assertRaises(ValueError):
            ids.format_instance_id("TOOLONG", 1)

    def test_stream_names(self) -> None:
        self.assertEqual(ids.stream_instance("JX-0001"), "instance:JX-0001")
        self.assertEqual(ids.stream_user("noura"), "user:noura")
        self.assertFalse(ids.is_outbox_stream(ids.aggregate_seq_stream("JX-0001")))

    def test_prefixed_ids_match_contract_format(self) -> None:
        pat = re.compile(r"^(task_|att_|turn_|art_|pend_|dr_|ev_)[0-9a-f]{16}$")
        for factory in (
            ids.new_task_id,
            ids.new_attempt_id,
            ids.new_turn_id,
            ids.new_artifact_id,
            ids.new_pending_id,
            ids.new_decision_id,
            ids.new_eval_run_id,
        ):
            with self.subTest(factory=factory.__name__):
                value = factory()
                self.assertRegex(value, pat)

    def test_instance_prefix_pattern_matches_workflow_spec(self) -> None:
        from aos.registry.kinds import WorkflowSpec

        self.assertEqual(
            ids.INSTANCE_PREFIX_RE.pattern,
            WorkflowSpec.model_json_schema()["properties"]["id_prefix"]["pattern"],
        )


class KernelProblemTests(unittest.TestCase):
    def test_problem_json_and_schema(self) -> None:
        app = FastAPI()
        register_problem_handlers(app)

        @app.get("/boom")
        def boom() -> None:
            raise KernelProblem("stale_version", 409, "Version changed", "Reload the page.", current_version=3)

        client = TestClient(app)
        r = client.get("/boom", headers={"X-Trace-Id": "a" * 32})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.headers["content-type"], "application/problem+json")
        body = r.json()
        jsonschema.validate(body, PROBLEM_SCHEMA)
        self.assertEqual(body["code"], "stale_version")
        self.assertEqual(body["current_version"], 3)
        self.assertEqual(body["trace_id"], "a" * 32)


@unittest.skipUnless(_pg.available(), "needs a local Postgres")
class M1MigrationTests(unittest.TestCase):
    db: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.sql(seed_sql(load_org(ORG_FILE)))

    @classmethod
    def tearDownClass(cls) -> None:
        _pg.drop(cls.db)

    @classmethod
    def sql(cls, statement: str, *, check: bool = True, user: str | None = None) -> subprocess.CompletedProcess:
        body = "set timezone = 'UTC';\n" + statement
        if user:
            url = _pg.kernel_url(cls.db).replace("aos_kernel:aos_kernel_dev", f"{user}:{user}_dev", 1)
            return subprocess.run(["psql", url, "-q", "-v", "ON_ERROR_STOP=1", "-At"], input=body, text=True,
                                  capture_output=True, check=check)
        return _pg.admin_sql(cls.db, body, check=check)

    def q(self, sql: str) -> str:
        return self.sql(sql).stdout.strip()

    def test_m1_tables_exist(self) -> None:
        for table in M1_TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.q(f"select to_regclass('{table}') is not null"), "t")

    def test_partial_unique_indexes(self) -> None:
        for name in M1_UNIQUE_INDEXES:
            with self.subTest(index=name):
                self.assertEqual(self.q(
                    f"select count(*) from pg_indexes where indexname = '{name}' and indexdef like '%UNIQUE%'"), "1")

    def test_guard_checks(self) -> None:
        for table, fragment in M1_CHECKS:
            with self.subTest(table=table):
                defs = self.q(f"select string_agg(pg_get_constraintdef(oid), ' | ') from pg_constraint "
                              f"where conrelid = '{table}'::regclass and contype = 'c'")
                self.assertIn(fragment, defs)

    def test_worker_role_cannot_read_m1_tables(self) -> None:
        for table in M1_TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.q(f"select has_table_privilege('aos_worker', '{table}', 'select')"), "f")

    def test_kernel_cannot_rewrite_execution_evidence(self) -> None:
        cases = (
            ("evidence.execution_events", "update evidence.execution_events set redacted_summary = 'x' where false;"),
            ("evidence.outbox", "update evidence.outbox set event_type = 'x' where false;"),
        )
        for table, upd in cases:
            with self.subTest(table=table, op="update"):
                res = self.sql(upd, user="aos_kernel", check=False)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("permission denied", res.stderr.lower())
            with self.subTest(table=table, op="delete"):
                res = self.sql(f"delete from {table} where false;", user="aos_kernel", check=False)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("permission denied", res.stderr.lower())


def _seed_instance_sql() -> str:
    return """
insert into registry.packs values ('org_demo', 'p_m1', 'platform_admin') on conflict do nothing;
insert into registry.pack_versions(org_id, pack_name, version, digest, source, status, validation, created_by)
values ('org_demo', 'p_m1', 1, 'd', 'test', 'published', '{}', 'platform_admin')
on conflict do nothing;
insert into work.instances (
  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, correlation_id, created_by
) select
  'JX-0001', 'org_demo', 'wf_demo', id, 'seat_demo', 1, 'Test job', 'intake', 'corr_m1_jx0001', 'person_a'
from registry.pack_versions where org_id = 'org_demo' and pack_name = 'p_m1' and version = 1
on conflict (id) do nothing;
"""


async def _seed_job(url: str) -> None:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(_seed_instance_sql())


def _outbox_rows(inst: str, *, to_state: str, version: int) -> list[OutboxRow]:
    return [
        OutboxRow(
            stream=ids.stream_instance(inst),
            event_type="instance.state_changed",
            instance_id=inst,
            audience={"roles": ["requester"]},
            data={"instance_id": inst, "from": "intake", "to": to_state, "version": version},
        ),
        OutboxRow(
            stream=ids.stream_user("person_a"),
            event_type="instance.state_changed",
            instance_id=inst,
            audience={"person_id": "person_a"},
            data={"instance_id": inst, "from": "intake", "to": to_state, "version": version},
        ),
    ]


async def _apply_state_bundle(
    url: str,
    *,
    expected_version: int,
    to_state: str,
    execution_events: int = 1,
    rollback: bool = False,
) -> None:
    await _seed_job(url)
    inst = "JX-0001"
    async with await psycopg.AsyncConnection.connect(url) as conn:
        try:
            async with conn.transaction():
                cur = await conn.execute(
                    "update work.instances set state = %s, version = version + 1 where id = %s and version = %s",
                    (to_state, inst, expected_version),
                )
                if cur.rowcount != 1:
                    raise AssertionError(f"expected one row updated, got {cur.rowcount}")
                for n in range(execution_events):
                    await outbox.write_execution_event(
                        conn,
                        ExecutionEventWrite(
                            org_id="org_demo",
                            run_id=inst,
                            event_type="RunCreated",
                            actor_kind="kernel",
                            actor_id="kernel",
                            correlation_id="corr_m1_jx0001",
                            redacted_summary=f"state changed for test ({n + 1})",
                        ),
                    )
                await outbox.append_outbox_many(
                    conn,
                    _outbox_rows(inst, to_state=to_state, version=expected_version + 1),
                )
                if rollback:
                    raise RuntimeError("rollback on purpose")
        except RuntimeError:
            if not rollback:
                raise


async def _collect_notifies(
    url: str,
    ready: asyncio.Event,
    *,
    until: Callable[[set[str]], bool],
    timeout: float = 3.0,
) -> set[str]:
    got: set[str] = set()
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(f"listen {outbox.OUTBOX_CHANNEL}")
        ready.set()
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if until(got):
                break
            try:
                async with asyncio.timeout(max(0.05, deadline - asyncio.get_running_loop().time())):
                    async for notify in conn.notifies():
                        got.add(notify.payload)
                        if until(got):
                            return got
            except TimeoutError:
                break
    return got


async def _notify_sentinel(url: str) -> None:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("select pg_notify(%s, %s)", (outbox.OUTBOX_CHANNEL, "sentinel"))


@unittest.skipUnless(_pg.available(), "needs a local Postgres")
class OutboxTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.url = _pg.kernel_url(self.db)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            await conn.execute(seed_sql(load_org(ORG_FILE)))

    async def asyncTearDown(self) -> None:
        _pg.drop(self.db)

    async def _counts(self) -> tuple[int, int, int, int]:
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            inst = await (await conn.execute(
                "select version, state from work.instances where id = 'JX-0001'")).fetchone()
            ev = await (await conn.execute("select count(*) as c from evidence.execution_events")).fetchone()
            ob = await (await conn.execute("select count(*) as c from evidence.outbox")).fetchone()
        version = int(inst["version"]) if inst else 0
        state = inst["state"] if inst else ""
        return version, int(ev["c"]), int(ob["c"]), state

    async def test_transaction_commits_state_event_and_two_outbox_rows(self) -> None:
        await _apply_state_bundle(self.url, expected_version=1, to_state="state_b")
        version, ev_count, ob_count, state = await self._counts()
        self.assertEqual(version, 2)
        self.assertEqual(state, "state_b")
        self.assertEqual(ev_count, 1)
        self.assertEqual(ob_count, 2)

        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            row = await (await conn.execute(
                "select event_id, org_id, run_id, aggregate_seq, event_type, actor_kind, actor_id,"
                " correlation_id, redacted_summary, occurred_at from evidence.execution_events")).fetchone()
            self.assertIsNotNone(row)
            occurred = row["occurred_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            doc = outbox.execution_event_document(
                row["event_id"],
                org_id=row["org_id"],
                run_id=row["run_id"],
                aggregate_seq=row["aggregate_seq"],
                event_type=row["event_type"],
                actor_kind=row["actor_kind"],
                actor_id=row["actor_id"],
                correlation_id=row["correlation_id"],
                redacted_summary=row["redacted_summary"],
                occurred_at=occurred,
            )
            jsonschema.validate(doc, EXECUTION_EVENT_SCHEMA)

    async def test_rolled_back_transaction_leaves_no_rows(self) -> None:
        await _apply_state_bundle(self.url, expected_version=1, to_state="state_b", rollback=True)
        version, ev_count, ob_count, state = await self._counts()
        self.assertEqual(version, 1)
        self.assertEqual(state, "intake")
        self.assertEqual(ev_count, 0)
        self.assertEqual(ob_count, 0)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            n = await (await conn.execute("select count(*) from evidence.stream_heads")).fetchone()
            self.assertEqual(n[0], 0)

    async def test_outbox_and_aggregate_seq_monotonic(self) -> None:
        inst = "JX-0001"
        inst_stream = ids.stream_instance(inst)
        user_stream = ids.stream_user("person_a")
        await _apply_state_bundle(self.url, expected_version=1, to_state="state_b")
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            rows = await (await conn.execute(
                "select stream, seq from evidence.outbox order by stream")).fetchall()
            self.assertEqual([(r["stream"], r["seq"]) for r in rows], [(inst_stream, 1), (user_stream, 1)])
            seqs = await (await conn.execute(
                "select aggregate_seq from evidence.execution_events order by aggregate_seq")).fetchall()
            self.assertEqual([r["aggregate_seq"] for r in seqs], [1])

        await _apply_state_bundle(self.url, expected_version=2, to_state="state_c", execution_events=2)
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            rows = await (await conn.execute(
                "select stream, seq from evidence.outbox order by stream, seq")).fetchall()
            self.assertEqual(
                [(r["stream"], r["seq"]) for r in rows],
                [(inst_stream, 1), (inst_stream, 2), (user_stream, 1), (user_stream, 2)],
            )
            seqs = await (await conn.execute(
                "select aggregate_seq from evidence.execution_events order by aggregate_seq")).fetchall()
            self.assertEqual([r["aggregate_seq"] for r in seqs], [1, 2, 3])

    async def test_append_outbox_rejects_run_stream(self) -> None:
        await _seed_job(self.url)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                with self.assertRaises(ValueError):
                    await outbox.append_outbox(
                        conn,
                        stream=ids.aggregate_seq_stream("JX-0001"),
                        event_type="instance.state_changed",
                        instance_id="JX-0001",
                        audience={"roles": ["requester"]},
                        data={},
                    )

    async def test_next_instance_id_from_db(self) -> None:
        await _seed_job(self.url)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            self.assertEqual(await ids.next_instance_id(conn, "JX"), "JX-0001")
            self.assertEqual(await ids.next_instance_id(conn, "JX"), "JX-0002")

    async def test_listen_receives_notify_on_commit_not_on_rollback(self) -> None:
        inst = "JX-0001"
        expected = {ids.stream_instance(inst), ids.stream_user("person_a")}

        ready = asyncio.Event()
        listen_task = asyncio.create_task(
            _collect_notifies(self.url, ready, until=lambda got: got == expected),
        )
        await ready.wait()
        await _apply_state_bundle(self.url, expected_version=1, to_state="state_b")
        self.assertEqual(await listen_task, expected)

        ready = asyncio.Event()
        listen_task = asyncio.create_task(
            _collect_notifies(self.url, ready, until=lambda got: got == {"sentinel"}),
        )
        await ready.wait()
        await _apply_state_bundle(self.url, expected_version=2, to_state="state_c", rollback=True)
        await _notify_sentinel(self.url)
        self.assertEqual(await listen_task, {"sentinel"})


if __name__ == "__main__":
    unittest.main()
