"""M2-BE-06: aos simulate and simulatePackVersion."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from aos import sim_worker
from aos.cli import main as cli_main
from aos.kernel import clock, ids, registry_store, simulate, workflow
from aos.kernel.events import raise_inbound_event
from aos.kernel.org import load_org, seed_sql
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO
from aos.kernel.simulate_stub import complete_admitted_attempt

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"
EXPECTED_PATH = [
    "intake",
    "shortlisting",
    "rfq_drafting",
    "rfq_sending",
    "awaiting_quotes",
    "comparison",
    "ordering",
    "closed",
]
EXPECTED_DEAD_ENDS = [
    "event.intent_identified: already raised",
    "approval (mailbox.send): not yet governed",
    "approval (erp_po.create, step 1): not yet governed",
    "approval (erp_po.create, step 2): not yet governed",
]


async def _sync_published(conn, packs_dir: Path) -> str:
    result = await registry_store.sync_pack(
        conn,
        org=ORG,
        packs_dir=packs_dir,
        name="procurement_demo",
        actor="test",
        source="test",
    )
    await conn.execute(
        "update registry.pack_versions set status = 'published' where id = %s",
        (result.pack_version_id,),
    )
    return result.pack_version_id


@unittest.skipUnless(_pg.available(), "needs Postgres")
class SimulateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-sim-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.url = _pg.kernel_url(self.db)
        self.conn = await psycopg.AsyncConnection.connect(self.url)
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await insert_seats_for_published_pack(
            self.conn,
            org=ORG,
            org_id=ORG_ID,
            pack_version_id=self.pack_version_id,
        )
        await self.conn.execute(
            "update registry.seats set state = 'ACTIVE' where org_id = %s and pack_version_id = %s",
            (ORG_ID, self.pack_version_id),
        )
        await self.conn.commit()

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def _baseline_counts(self) -> dict[str, int]:
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            inst = await (await conn.execute("select count(*) from work.instances")).fetchone()
            tasks = await (await conn.execute("select count(*) from work.tasks")).fetchone()
            audit = await (await conn.execute("select count(*) from evidence.audit_events")).fetchone()
            seq = await (await conn.execute("select last_value from work.instance_number")).fetchone()
            return {
                "instances": int(inst[0]),
                "tasks": int(tasks[0]),
                "audit": int(audit[0]),
                "instance_number": int(seq[0]),
            }

    async def test_quick_quote_simulation_happy_path(self) -> None:
        before = await self._baseline_counts()
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            try:
                async with conn.transaction():
                    report = await simulate.run_simulation(
                        conn,
                        ORG,
                        org_id=ORG_ID,
                        pack_version_id=self.pack_version_id,
                        workflow_name=WORKFLOW,
                        script_name="dry_run_script",
                        packs_dir=self.packs_dir,
                    )
                    raise simulate.SimulationRollback(report)
            except simulate.SimulationRollback as exc:
                report = exc.report
        after = await self._baseline_counts()
        self.assertEqual(before, after)
        self.assertEqual(report["reached"], "closed")
        self.assertEqual(report["path"], EXPECTED_PATH)
        self.assertEqual(report["committed_effects"], 0)
        self.assertEqual(report["model"], "fake")
        self.assertEqual(report["dead_ends"], EXPECTED_DEAD_ENDS)

        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            cur = await conn.execute(
                "select template from work.tasks where kind = 'task' order by template, created_at"
            )
            templates = [r[0] for r in await cur.fetchall()]
        self.assertEqual(templates, [])

    async def test_task_templates_once(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            try:
                async with conn.transaction():
                    report = await simulate.run_simulation(
                        conn,
                        ORG,
                        org_id=ORG_ID,
                        pack_version_id=self.pack_version_id,
                        workflow_name=WORKFLOW,
                        script_name="dry_run_script",
                        packs_dir=self.packs_dir,
                    )
                    inst_cur = await conn.execute(
                        "select id from work.instances where id like 'QQ-SIM-%' limit 1"
                    )
                    inst = (await inst_cur.fetchone())[0]
                    tcur = await conn.execute(
                        "select template from work.tasks where instance_id = %s and kind = 'task'"
                        " order by created_at",
                        (inst,),
                    )
                    templates = [r[0] for r in await tcur.fetchall()]
                    raise simulate.SimulationRollback({"templates": templates, **report})
            except simulate.SimulationRollback as exc:
                templates = exc.report["templates"]
        counts = Counter(templates)
        self.assertEqual(counts["supplier_lookup"], 2, "the requester's answer changes the brief after the first ranking")
        self.assertEqual(counts["rfq_draft"], 1)
        self.assertEqual(counts["rfq_send"], 1)
        self.assertEqual(counts["quote_comparison"], 1)
        self.assertEqual(counts["po_create"], 1)
        self.assertEqual(counts["quote_triage"], 2)
        self.assertEqual(counts["request_intake"], 1)

    async def test_simulate_pack_version_matches(self) -> None:
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(self.url, open=False)
        await pool.open()
        try:
            api_report = await simulate.run_simulation_rolled_back(
                pool,
                ORG,
                org_id=ORG_ID,
                pack_version_id=self.pack_version_id,
                workflow_name=WORKFLOW,
                script_name="dry_run_script",
                packs_dir=self.packs_dir,
            )
        finally:
            await pool.close()
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            try:
                async with conn.transaction():
                    direct = await simulate.run_simulation(
                        conn,
                        ORG,
                        org_id=ORG_ID,
                        pack_version_id=self.pack_version_id,
                        workflow_name=WORKFLOW,
                        script_name="dry_run_script",
                        packs_dir=self.packs_dir,
                    )
                    raise simulate.SimulationRollback(direct)
            except simulate.SimulationRollback as exc:
                direct = exc.report
        self.assertEqual(api_report, direct)

    async def test_dry_run_through_the_fake_model_with_verifiers(self) -> None:
        _pg.require_runtime_extra()
        clock.set_frozen_wall(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
        self.addCleanup(clock.set_frozen_wall, None)
        before = await self._baseline_counts()
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            try:
                async with conn.transaction():
                    report = await simulate.run_simulation(
                        conn,
                        ORG,
                        org_id=ORG_ID,
                        pack_version_id=self.pack_version_id,
                        workflow_name=WORKFLOW,
                        script_name="dry_run_script",
                        packs_dir=self.packs_dir,
                        run_attempt=sim_worker.run_attempt,
                    )
                    cur = await conn.execute(
                        "select a.artifact_type, a.key, v.version, v.verification->>'verifier',"
                        " v.verification->>'verdict' from work.artifacts a join work.artifact_versions v"
                        " on v.artifact_id = a.id and v.version = a.latest_version"
                        " where a.instance_id like 'QQ-SIM-%' and a.artifact_type in"
                        " ('brief', 'supplier_list', 'rfq_email') order by a.artifact_type, a.key"
                    )
                    outputs = [tuple(r) for r in await cur.fetchall()]
                    cur = await conn.execute(
                        "select t.template, count(*) from work.attempts a join work.tasks t on t.id = a.task_id"
                        " where t.instance_id like 'QQ-SIM-%%' and a.worker_id = %s group by t.template"
                        " order by t.template",
                        (sim_worker.WORKER_ID,),
                    )
                    graph_runs = dict(await cur.fetchall())
                    raise simulate.SimulationRollback({**report, "outputs": outputs, "graph_runs": graph_runs})
            except simulate.SimulationRollback as exc:
                report = exc.report
        self.assertEqual(await self._baseline_counts(), before)
        self.assertEqual(report["reached"], "closed")
        self.assertEqual(report["path"], EXPECTED_PATH)
        self.assertEqual(report["dead_ends"], EXPECTED_DEAD_ENDS)
        self.assertEqual(
            report["graph_runs"],
            {"request_intake": 2, "rfq_draft": 1, "supplier_lookup": 2},
            "Tasks with a script ran through the graphs: the intake asked once and resumed on the answer, and the"
            " search ranked again against the brief the answer changed",
        )
        self.assertEqual(
            [o for o in report["outputs"] if o[3]],
            [
                ("brief", "", 2, "brief_schema", "PASS"),
                ("rfq_email", "SUP-10217", 1, "leak_check", "PASS"),
                ("rfq_email", "SUP-10355", 1, "leak_check", "PASS"),
                ("rfq_email", "SUP-10482", 1, "leak_check", "PASS"),
                ("supplier_list", "", 2, "sources_cited", "PASS"),
            ],
            "every graph-made output passed its verifier; the send Task (no script yet) left a stub draft",
        )

    def test_cli_simulate_reaches_closed(self) -> None:
        # AOS_DATABASE_URL is what Settings reads; with the wrong name the CLI fell back to the default database
        # (the developer's real one locally, nothing in CI).
        env = {"PYTHONPATH": f"{REPO}/backend/src:{REPO}/backend/.vendor", "AOS_DATABASE_URL": self.url}
        pack = self.packs_dir / "procurement_demo"
        rc = subprocess.run(
            [sys.executable, "-m", "aos.cli", "simulate", str(pack), "--workflow", WORKFLOW, "--json"],
            cwd=REPO / "backend",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(rc.returncode, 0, rc.stderr or rc.stdout)
        report = json.loads(rc.stdout)
        self.assertEqual(report["reached"], "closed")


@unittest.skipUnless(_pg.available(), "needs Postgres")
class WorkflowTaskCompletedEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-tc-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await self.conn.commit()

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_rfq_draft_completion_moves_to_rfq_sending(self) -> None:
        inst = "QQ-SIM-TC1"  # completed through the simulation stub, which only runs on simulated jobs
        async with self.conn.transaction():
            await self.conn.execute(
                """
                insert into work.instances (
                  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                  attributes, created_by, correlation_id, status
                ) values (%s, %s, %s, %s, %s, 1, 'T', 'rfq_drafting', 3, '{"shortlist_count": 3}', 'noura', 'c1', 'running')
                """,
                (inst, ORG_ID, WORKFLOW, self.pack_version_id, SEAT),
            )
            await self.conn.execute(
                "insert into work.participants (instance_id, role, person_id, bound_by)"
                " values (%s, 'buyer', 'noura', 'claim')",
                (inst,),
            )
            task_id = ids.new_task_id()
            from aos.kernel import contracts

            defs = await workflow._load_definitions(self.conn, self.pack_version_id)
            pack_cur = await self.conn.execute(
                "select pack_name, version, digest from registry.pack_versions where id = %s",
                (self.pack_version_id,),
            )
            pn, pv, pd = await pack_cur.fetchone()
            seat_doc = defs.get("Seat", {}).get(SEAT) or {}
            contract = contracts.build_task_contract(
                packs_dir=self.packs_dir,
                pack_name=pn,
                pack_version=int(pv),
                pack_digest=pd,
                defs=defs,
                org_id=ORG_ID,
                instance_id=inst,
                task_id=task_id,
                seat_name=SEAT,
                seat_version=1,
                seat_doc=seat_doc,
                workflow_name=WORKFLOW,
                template={
                    "template": "rfq_draft",
                    "skill": "rfq_authoring",
                    "work_type": "document_draft",
                    "verifier": "leak_check",
                    "on_behalf_of": "buyer",
                },
                participant_role="buyer",
                person_id="noura",
                seat_limits=(seat_doc.get("spec") or {}).get("limits") or {},
            )
            await self.conn.execute(
                """
                insert into work.tasks (
                  id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash, max_attempts, attempts_used, fencing_token
                ) values (%s, %s, 'task', 'rfq_draft', 'rfq_authoring', 'document_draft', 'leak_check', 'RUNNING', %s, %s, 3, 1, 1)
                """,
                (task_id, inst, json.dumps(contract), contract["contract_hash"]),
            )
            attempt_id = ids.new_attempt_id()
            await self.conn.execute(
                "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd)"
                " values (%s, %s, 1, 1, 'ADMITTED', 0)",
                (attempt_id, task_id),
            )
            await complete_admitted_attempt(
                self.conn,
                org=ORG,
                org_id=ORG_ID,
                attempt_id=attempt_id,
                packs_dir=self.packs_dir,
            )
            cur = await self.conn.execute("select state from work.instances where id = %s", (inst,))
            self.assertEqual((await cur.fetchone())[0], "rfq_sending")


@unittest.skipUnless(_pg.available(), "needs Postgres")
class RaiseInboundEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-inb-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await self.conn.commit()

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_mail_in_awaiting_quotes_creates_triage_task(self) -> None:
        inst = "QQ-IN1"
        async with self.conn.transaction():
            await self.conn.execute(
                """
                insert into work.instances (
                  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                  attributes, created_by, correlation_id, status
                ) values (%s, %s, %s, %s, %s, 1, 'T', 'awaiting_quotes', 5, '{}', 'noura', 'c2', 'running')
                """,
                (inst, ORG_ID, WORKFLOW, self.pack_version_id, SEAT),
            )
            await self.conn.execute(
                "insert into work.participants (instance_id, role, person_id, bound_by)"
                " values (%s, 'buyer', 'noura', 'claim')",
                (inst,),
            )
            ok = await raise_inbound_event(
                self.conn, ORG, inst, "mail.message_received", packs_dir=self.packs_dir
            )
            self.assertTrue(ok)
            cur = await self.conn.execute(
                "select template from work.tasks where instance_id = %s and template = 'quote_triage'",
                (inst,),
            )
            self.assertEqual(len(await cur.fetchall()), 1)

    async def test_mail_in_intake_is_no_match(self) -> None:
        inst = "QQ-IN2"
        async with self.conn.transaction():
            await self.conn.execute(
                """
                insert into work.instances (
                  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                  attributes, created_by, correlation_id, status
                ) values (%s, %s, %s, %s, %s, 1, 'T', 'intake', 1, '{}', 'faisal', 'c3', 'running')
                """,
                (inst, ORG_ID, WORKFLOW, self.pack_version_id, SEAT),
            )
            ok = await raise_inbound_event(
                self.conn, ORG, inst, "mail.message_received", packs_dir=self.packs_dir
            )
            self.assertFalse(ok)
            cur = await self.conn.execute(
                "select attributes->>'reason' from evidence.execution_events"
                " where run_id = %s and event_type = 'WorkflowEventIgnored' order by aggregate_seq desc limit 1",
                (inst,),
            )
            self.assertEqual((await cur.fetchone())[0], "no_match")
