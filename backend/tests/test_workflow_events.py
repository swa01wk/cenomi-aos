"""M2-BE-02: pack events, parallel regions, join guards and re-run."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg

from aos.kernel import artifacts, decisions, events, ids, tasks, verify, workflow
from aos.kernel import worker_submit
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import load_org, seed_sql
from aos.registry.loader import parse_yaml
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO
from aos.kernel.worker_fence import ClaimedAttempt

from . import _pg
from .test_validate import PackCase

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


async def _sync_published(conn, packs_dir: Path) -> str:
    result = await sync_pack(
        conn,
        org=ORG,
        packs_dir=packs_dir,
        name="procurement_demo",
        actor="platform_admin",
        source="test",
    )
    await conn.execute(
        "update registry.pack_versions set status = 'published' where id = %s",
        (result.pack_version_id,),
    )
    return result.pack_version_id


async def _insert_instance(
    conn,
    *,
    instance_id: str,
    pack_version_id: str,
    state: str = "intake",
    status: str = "running",
    attributes: dict | None = None,
    with_buyer: bool = True,
) -> None:
    attrs = attributes or {}
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version, status,
          attributes, created_by, correlation_id
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, 1, %s, %s, 'faisal', %s)
        """,
        (
            instance_id,
            ORG_ID,
            WORKFLOW,
            pack_version_id,
            SEAT,
            state,
            status,
            json.dumps(attrs),
            f"corr_{instance_id}",
        ),
    )
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, 'requester', 'faisal', 'creation')",
        (instance_id,),
    )
    if with_buyer:
        await conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, 'buyer', 'noura', 'claim')",
            (instance_id,),
        )


def _brief_content(*, category: str = "CAT-1") -> dict:
    return {
        "title": "Trolley",
        "category": category,
        "quantity": 2,
        "specification": "spec",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh",
    }


def _brief_no_category() -> dict:
    return {
        "title": "Trolley",
        "quantity": 2,
        "specification": "spec",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh",
    }


def _gate(instance_id: str, *, task_id: str | None = None) -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id="att_evt",
        task_id=task_id or ids.new_task_id(),
        instance_id=instance_id,
        org_id=ORG_ID,
        seat=SEAT,
        seat_version=1,
        correlation_id=f"corr_{instance_id}",
        fencing_token=1,
        attempt_n=1,
        turn_id=None,
        kind="task",
        contract={"expected_outputs": [{"artifact_type": "brief"}]},
        reserved_usd=0,
        usage={},
        worker_id="worker_test",
        task_state="RUNNING",
        attempts_used=1,
        max_attempts=3,
    )


async def _count_events(conn, instance_id: str, event_type: str) -> int:
    cur = await conn.execute(
        "select count(*) from evidence.execution_events where run_id = %s and event_type = %s",
        (instance_id, event_type),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _save_brief_draft(
    conn,
    *,
    instance_id: str,
    pack_version_id: str,
    packs_dir: Path,
    content: dict,
    artifact_id: str | None = None,
) -> None:
    defs = await workflow._load_definitions(conn, pack_version_id)
    body: dict = {"artifact_type": "brief", "content": content}
    if artifact_id:
        body["artifact_id"] = artifact_id
        body["base_version"] = 1
    await artifacts.save_draft_from_attempt(
        conn,
        org=ORG,
        gate=_gate(instance_id),
        body=body,
        defs=defs,
        packs_dir=packs_dir,
    )


def _supplier_list_content() -> dict:
    return {
        "rows": [
            {
                "rank": 1,
                "supplier": "Najd",
                "supplier_id": "s1",
                "score": 88.0,
                "sources": [],
            }
        ]
    }


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkflowEventsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-evt-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_intent_not_raised_without_category(self) -> None:
        inst = "QQ-E01"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _save_brief_draft(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            content=_brief_no_category(),
        )
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 0)
        cur = await self.conn.execute("select count(*) from work.regions where instance_id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], 0)

    async def test_intent_raised_once_and_starts_discovery(self) -> None:
        inst = "QQ-E02"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _save_brief_draft(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            content=_brief_content(),
        )
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 1)
        cur = await self.conn.execute(
            "select name, state, started_with from work.regions where instance_id = %s",
            (inst,),
        )
        row = await cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "discovery")
        self.assertEqual(row[1], "running")
        self.assertEqual(row[2], {})
        cur = await self.conn.execute(
            "select template, region, state, contract->'on_behalf_of'->>'role' as role"
            " from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        task = await cur.fetchone()
        self.assertIsNotNone(task)
        self.assertEqual(task[0], "supplier_lookup")
        self.assertEqual(task[1], "discovery")
        self.assertEqual(task[2], "CREATED")
        self.assertEqual(task[3], "buyer")

        cur = await self.conn.execute(
            "select id from work.artifacts where instance_id = %s and artifact_type = 'brief'",
            (inst,),
        )
        aid = (await cur.fetchone())[0]
        await _save_brief_draft(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            content=_brief_content(category="CAT-2"),
            artifact_id=aid,
        )
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 1)

    async def test_raise_on_closed_job_is_no_op(self) -> None:
        inst = "QQ-E03"
        await _insert_instance(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            state="closed",
            status="closed",
        )
        fired = await events.raise_event(
            self.conn,
            ORG,
            inst,
            "intent_identified",
            packs_dir=self.packs_dir,
            trigger="test",
        )
        self.assertFalse(fired)
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 0)

    async def test_undeclared_event_raises(self) -> None:
        inst = "QQ-E04"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        with self.assertRaises(events.WorkflowEventError):
            await events.raise_event(
                self.conn,
                ORG,
                inst,
                "not_declared",
                packs_dir=self.packs_dir,
                trigger="test",
            )

    async def test_region_done_opens_shortlist_decision(self) -> None:
        inst = "QQ-E05"
        await _insert_instance(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            state="shortlisting",
        )
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)',
                    '{"brief_version": 1}'::jsonb)
            """,
            (inst,),
        )
        await self.conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (json.dumps({"brief_version": 1}), inst),
        )
        aid = ids.new_artifact_id()
        content = _supplier_list_content()
        ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'supplier_list', '', 'Suppliers', 'draft', 1)",
            (aid, inst),
        )
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 1, %s, %s, 'attempt', 'att_x', '[]', '[]')",
            (aid, json.dumps(content), ch),
        )
        task_id = ids.new_task_id()
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, region, state, contract, contract_hash, max_attempts
            ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'discovery', 'COMPLETED', '{}', 'h', 3)
            """,
            (task_id, inst),
        )
        await events.on_workflow_task_completed(
            self.conn,
            ORG,
            instance_id=inst,
            task_id=task_id,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute(
            "select state from work.regions where instance_id = %s and name = 'discovery'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], "done")
        cur = await self.conn.execute(
            "select event from work.pending_items where instance_id = %s and status = 'open'",
            (inst,),
        )
        row = await cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "decision.shortlist_confirmed")

    async def test_all_quotes_received_when_attributes_match(self) -> None:
        inst = "QQ-E06"
        await _insert_instance(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            state="awaiting_quotes",
            attributes={"quote_count": 1, "invited_count": 2},
        )
        await events.evaluate_attribute_triggers(
            self.conn,
            ORG,
            inst,
            changed={"quote_count"},
            packs_dir=self.packs_dir,
        )
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 0)

        await self.conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (json.dumps({"quote_count": 2, "invited_count": 2}), inst),
        )
        await events.evaluate_attribute_triggers(
            self.conn,
            ORG,
            inst,
            changed={"quote_count", "invited_count"},
            packs_dir=self.packs_dir,
        )
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 1)
        cur = await self.conn.execute("select state from work.instances where id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], "comparison")

@unittest.skipUnless(_pg.available(), "no local Postgres")
class DecisionEventOrderTests(unittest.IsolatedAsyncioTestCase):
    """decide_pending applies decision.* before attribute-derived domain events."""

    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-order-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        wf_path = self.packs_dir / "procurement_demo" / "workflows" / "quick_quote.yaml"
        doc = parse_yaml(wf_path.read_text())
        doc["spec"]["events"]["dummy_follow"] = {
            "on_attributes": ["shortlist_count"],
            "when": "attr.shortlist_count >= 3",
            "once": True,
        }
        doc["spec"]["transitions"].append(
            {"from": "shortlisting", "to": "intake", "on": "event.dummy_follow"},
        )
        import yaml

        wf_path.write_text(yaml.safe_dump(doc, sort_keys=False))
        pack_yaml = self.packs_dir / "procurement_demo" / "pack.yaml"
        lines = pack_yaml.read_text().splitlines()
        pack_yaml.write_text(
            "\n".join(
                "metadata: {name: procurement_demo, version: 2, owner: head_of_procurement}"
                if line.startswith("metadata:") and "procurement_demo" in line
                else line
                for line in lines
            )
            + "\n"
        )
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_decision_transition_before_attribute_event(self) -> None:
        inst = "QQ-E07"
        await _insert_instance(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            state="shortlisting",
        )
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)',
                    '{"brief_version": 1}'::jsonb)
            """,
            (inst,),
        )
        await self.conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (json.dumps({"brief_version": 1}), inst),
        )
        aid = ids.new_artifact_id()
        rows = [_supplier_list_content()["rows"][0].copy() for _ in range(3)]
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
            row["supplier_id"] = f"s{i}"
        content = {"rows": rows}
        ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'supplier_list', '', 'Suppliers', 'draft', 1)",
            (aid, inst),
        )
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 1, %s, %s, 'attempt', 'att_x', '[]', '[]')",
            (aid, json.dumps(content), ch),
        )
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        pending_id = opened[0]
        await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            pending_id,
            "noura",
            {
                "value": "confirm",
                "expected_version": 1,
                "artifact_version": 1,
                "selection": ["s1", "s2", "s3"],
            },
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute("select state from work.instances where id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], "rfq_drafting")
        self.assertGreaterEqual(await _count_events(self.conn, inst, "WorkflowEventRaised"), 1)


class EventTriggerValidationTests(PackCase):
    def test_event_both_triggers_fails(self) -> None:
        def fn(d):
            d["spec"]["events"]["bad"] = {
                "on_artifact": "brief",
                "on_attributes": ["quote_count"],
                "when": "true",
            }

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_SCHEMA")

    def test_event_unknown_artifact_type(self) -> None:
        def fn(d):
            d["spec"]["events"]["bad"] = {
                "on_artifact": "not_a_type",
                "when": "size(artifact.title) > 0",
            }

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_REF")

    def test_event_undeclared_attribute(self) -> None:
        def fn(d):
            d["spec"]["events"]["bad"] = {
                "on_attributes": ["missing_attr"],
                "when": "attr.missing_attr > 0",
            }

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_ATTRIBUTE")

    def test_event_bad_expression(self) -> None:
        def fn(d):
            d["spec"]["events"]["bad"] = {
                "on_artifact": "brief",
                "when": "attr.not_there > 0",
            }

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_ATTRIBUTE")

    def test_join_guard_same_without_artifact_version_setter(self) -> None:
        def fn(d):
            d["spec"]["attributes"]["orphan_version"] = "int"
            d["spec"]["parallel"][0]["join_guard"] = "same(orphan_version)"

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_EXPRESSION")


async def _insert_request_intake_done(conn, instance_id: str) -> None:
    tid = ids.new_task_id()
    await conn.execute(
        """
        insert into work.tasks (
          id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
        ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'COMPLETED', '{}', 'h', 3)
        """,
        (tid, instance_id),
    )


async def _latest_lookup_task(conn, instance_id: str) -> str:
    cur = await conn.execute(
        "select id from work.tasks where instance_id = %s and template = 'supplier_lookup'"
        " and state != 'COMPLETED' order by created_at desc, id desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is not None:
        return str(row[0])
    cur = await conn.execute(
        "select id from work.tasks where instance_id = %s and template = 'supplier_lookup'"
        " order by created_at desc, id desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    assert row is not None
    return str(row[0])


async def _claim_and_admit_lookup(
    conn,
    *,
    instance_id: str,
    task_id: str,
    contract: dict,
) -> tuple[str, int]:
    attempt_id = ids.new_attempt_id()
    cur = await conn.execute(
        "select attempts_used from work.tasks where id = %s for update",
        (task_id,),
    )
    attempts_used = int((await cur.fetchone())[0])
    await conn.execute(
        "update work.tasks set state = 'READY', contract = %s, contract_hash = %s where id = %s",
        (json.dumps(contract), contract["contract_hash"], task_id),
    )
    await tasks.admit_attempt(
        conn,
        org_id=ORG_ID,
        seat=SEAT,
        daily_limit_usd=100.0,
        task_id=task_id,
        attempt_id=attempt_id,
        turn_id=None,
        attempt_n=attempts_used + 1,
        reservation_usd=0.5,
    )
    await conn.execute(
        "update work.attempts set state = 'CLAIMED', worker_id = 'w-test' where id = %s",
        (attempt_id,),
    )
    cur = await conn.execute("select fencing_token from work.tasks where id = %s", (task_id,))
    return attempt_id, int((await cur.fetchone())[0])


async def _save_supplier_list_for_attempt(
    conn,
    *,
    instance_id: str,
    pack_version_id: str,
    packs_dir: Path,
    task_id: str,
    attempt_id: str,
) -> dict:
    gate = ClaimedAttempt(
        attempt_id=attempt_id,
        task_id=task_id,
        instance_id=instance_id,
        org_id=ORG_ID,
        seat=SEAT,
        seat_version=1,
        correlation_id=f"corr_{instance_id}",
        fencing_token=1,
        attempt_n=1,
        turn_id=None,
        kind="task",
        contract={"expected_outputs": [{"artifact_type": "supplier_list"}]},
        reserved_usd=0,
        usage={},
        worker_id="w-test",
        task_state="RUNNING",
        attempts_used=1,
        max_attempts=3,
    )
    defs = await workflow._load_definitions(conn, pack_version_id)
    body = {"artifact_type": "supplier_list", "content": _supplier_list_content()}
    saved = await artifacts.save_draft_from_attempt(
        conn, org=ORG, gate=gate, body=body, defs=defs, packs_dir=packs_dir
    )
    return saved


async def _submit_lookup_pass(
    conn,
    *,
    attempt_id: str,
    task_id: str,
    contract: dict,
    output_ref: dict,
    packs_dir: Path,
    fencing_token: int,
) -> None:
    await worker_submit.submit_result(
        conn,
        org=ORG,
        org_id=ORG_ID,
        attempt_id=attempt_id,
        worker_id="w-test",
        fencing_token=fencing_token,
        result={
            "attempt_id": attempt_id,
            "contract_id": contract["contract_id"],
            "status": "completed",
            "summary": "Ranked suppliers.",
            "output_artifact_refs": [output_ref],
            "input_versions": {},
        },
        packs_dir=packs_dir,
    )


def _pass_sources_cited() -> None:
    def _handler(_conn, _gate, _result, _defs):  # type: ignore[no-untyped-def]
        return "PASS", []

    verify.register_implementation("aos.verifiers.sources_cited", _handler)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ParallelJoinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-join-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await self.conn.commit()
        _pass_sources_cited()

    async def asyncTearDown(self) -> None:
        verify.unregister_implementation("aos.verifiers.sources_cited")
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def _build_lookup_contract(self, conn, instance_id: str, task_id: str) -> dict:
        defs = await workflow._load_definitions(conn, self.pack_version_id)
        pack_cur = await conn.execute(
            "select pack_name, version, digest from registry.pack_versions where id = %s",
            (self.pack_version_id,),
        )
        pn, pv, pd = await pack_cur.fetchone()
        seat_doc = defs.get("Seat", {}).get(SEAT) or {}
        from aos.kernel import contracts

        return contracts.build_task_contract(
            packs_dir=self.packs_dir,
            pack_name=pn,
            pack_version=int(pv),
            pack_digest=pd,
            defs=defs,
            org_id=ORG_ID,
            instance_id=instance_id,
            task_id=task_id,
            seat_name=SEAT,
            seat_version=1,
            seat_doc=seat_doc,
            workflow_name=WORKFLOW,
            template={
                "template": "supplier_lookup",
                "skill": "supplier_lookup",
                "work_type": "analysis",
                "verifier": "sources_cited",
                "on_behalf_of": "buyer",
            },
            participant_role="buyer",
            person_id="noura",
            seat_limits=(seat_doc.get("spec") or {}).get("limits") or {},
        )

    async def _assert_c03_end_state(self, conn, inst: str) -> None:
        cur = await conn.execute("select state from work.instances where id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], "shortlisting")
        cur = await conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 2)
        cur = await conn.execute(
            "select state from work.regions where instance_id = %s and name = 'discovery'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], "running")
        cur = await conn.execute(
            "select count(*) from work.pending_items where instance_id = %s and status = 'open'"
            " and event = 'decision.shortlist_confirmed'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 0)

    async def test_started_with_on_admit_and_overwrite(self) -> None:
        inst = "QQ-J01"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
        )
        aid = ids.new_artifact_id()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'brief', '', 'Brief', 'draft', 2)",
            (aid, inst),
        )
        for v in (1, 2):
            ch = __import__("hashlib").sha256(_canonical_json(_brief_v(v))).hexdigest()
            await self.conn.execute(
                "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
                " produced_by_kind, produced_by, inputs, sources)"
                " values (%s, %s, %s, %s, 'person', 'faisal', '[]', '[]')",
                (aid, v, json.dumps(_brief_v(v)), ch),
            )
        task_id = ids.new_task_id()
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash, max_attempts
            ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'sources_cited', 'discovery',
                      'CREATED', '{}', 'h', 3)
            """,
            (task_id, inst),
        )
        await tasks.admit_attempt(
            self.conn,
            org_id=ORG_ID,
            seat=SEAT,
            daily_limit_usd=100.0,
            task_id=task_id,
            attempt_id=ids.new_attempt_id(),
            turn_id=None,
            attempt_n=1,
            reservation_usd=0.5,
        )
        cur = await self.conn.execute(
            "select started_with from work.regions where instance_id = %s and name = 'discovery'",
            (inst,),
        )
        sw = (await cur.fetchone())[0]
        self.assertEqual(sw.get("brief_version"), 2)
        await self.conn.execute(
            "update work.artifacts set latest_version = 3 where id = %s",
            (aid,),
        )
        ch3 = __import__("hashlib").sha256(_canonical_json(_brief_v(3))).hexdigest()
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 3, %s, %s, 'person', 'faisal', '[]', '[]')",
            (aid, json.dumps(_brief_v(3)), ch3),
        )
        await self.conn.execute(
            "update work.attempts set state = 'ENDED', outcome = 'expired' where task_id = %s",
            (task_id,),
        )
        await self.conn.execute("update work.tasks set state = 'READY' where id = %s", (task_id,))
        await tasks.admit_attempt(
            self.conn,
            org_id=ORG_ID,
            seat=SEAT,
            daily_limit_usd=100.0,
            task_id=task_id,
            attempt_id=ids.new_attempt_id(),
            turn_id=None,
            attempt_n=2,
            reservation_usd=0.5,
        )
        cur = await self.conn.execute(
            "select started_with from work.regions where instance_id = %s and name = 'discovery'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0].get("brief_version"), 3)

    async def test_old_task_admit_does_not_update_started_with(self) -> None:
        inst = "QQ-J02"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)',
                    '{"brief_version": 2}'::jsonb)
            """,
            (inst,),
        )
        old_task = ids.new_task_id()
        new_task = ids.new_task_id()
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash,
              max_attempts, created_at
            ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'sources_cited', 'discovery',
                      'COMPLETED', '{}', 'h', 3, now() - interval '1 hour')
            """,
            (old_task, inst),
        )
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash,
              max_attempts, created_at
            ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'sources_cited', 'discovery',
                      'CREATED', '{}', 'h', 3, now())
            """,
            (new_task, inst),
        )
        aid = ids.new_artifact_id()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'brief', '', 'Brief', 'draft', 3)",
            (aid, inst),
        )
        for v in (1, 2, 3):
            ch = __import__("hashlib").sha256(_canonical_json(_brief_v(v))).hexdigest()
            await self.conn.execute(
                "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
                " produced_by_kind, produced_by, inputs, sources)"
                " values (%s, %s, %s, %s, 'person', 'faisal', '[]', '[]')",
                (aid, v, json.dumps(_brief_v(v)), ch),
            )
        await tasks.admit_attempt(
            self.conn,
            org_id=ORG_ID,
            seat=SEAT,
            daily_limit_usd=100.0,
            task_id=old_task,
            attempt_id=ids.new_attempt_id(),
            turn_id=None,
            attempt_n=2,
            reservation_usd=0.5,
        )
        cur = await self.conn.execute(
            "select started_with from work.regions where instance_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0].get("brief_version"), 2)

    async def test_late_old_completion_does_not_mark_region_done(self) -> None:
        inst = "QQ-J03"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
        )
        old_task = ids.new_task_id()
        new_task = ids.new_task_id()
        for tid, st in ((old_task, "RUNNING"), (new_task, "RUNNING")):
            await self.conn.execute(
                """
                insert into work.tasks (
                  id, instance_id, kind, template, skill, work_type, region, state, contract, contract_hash, max_attempts,
                  created_at
                ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'discovery', %s,
                          '{}', 'h', 3, now())
                """,
                (tid, inst, st),
            )
        await self.conn.execute(
            "update work.tasks set created_at = now() - interval '1 hour' where id = %s",
            (old_task,),
        )
        await self.conn.execute("update work.tasks set state = 'COMPLETED' where id = %s", (old_task,))
        await events.on_workflow_task_completed(
            self.conn, ORG, instance_id=inst, task_id=old_task, packs_dir=self.packs_dir
        )
        cur = await self.conn.execute(
            "select state from work.regions where instance_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], "running")

    async def test_join_pending_on_transition_out_of_join(self) -> None:
        inst = "QQ-J04"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting")
        await self.conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (json.dumps({"shortlist_count": 3, "brief_version": 1}), inst),
        )
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
        )
        await _insert_supplier_list_artifact(self.conn, inst, sids=("s1", "s2", "s3"))
        r = await workflow.apply_event(
            self.conn,
            inst,
            "decision.shortlist_confirmed",
            by_role="buyer",
            packs_dir=self.packs_dir,
            org=ORG,
            actor={"kind": "person", "id": "noura"},
        )
        self.assertFalse(r.applied)
        self.assertEqual(r.reason, "join_pending")
        self.assertEqual(await _count_events(self.conn, inst, "WorkflowEventIgnored"), 1)

    async def test_no_rerun_when_guard_holds_at_join(self) -> None:
        inst = "QQ-J05"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="intake")
        await _insert_request_intake_done(self.conn, inst)
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)',
                    '{"brief_version": 2}'::jsonb)
            """,
            (inst,),
        )
        await self.conn.execute(
            "insert into work.tasks (id, instance_id, kind, template, skill, work_type, region, state,"
            " contract, contract_hash, max_attempts)"
            " values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'discovery', 'COMPLETED',"
            " '{}', 'h', 3)",
            (ids.new_task_id(), inst),
        )
        await _insert_brief_two_versions(self.conn, inst)
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select id from work.pending_items where instance_id = %s and event = 'decision.brief_confirmed'",
            (inst,),
        )
        pending_id = (await cur.fetchone())[0]
        await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            pending_id,
            "faisal",
            {"value": "confirm", "expected_version": 1, "artifact_version": 2},
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 1)

    async def test_regions_joined_on_exit_and_not_rerun(self) -> None:
        inst = "QQ-J06"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting")
        await self.conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (json.dumps({"brief_version": 2, "shortlist_count": 3}), inst),
        )
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)',
                    '{"brief_version": 2}'::jsonb)
            """,
            (inst,),
        )
        await _insert_supplier_list_artifact(self.conn, inst, sids=("s1", "s2", "s3"))
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            opened[0],
            "noura",
            {
                "value": "confirm",
                "expected_version": 1,
                "artifact_version": 1,
                "selection": ["s1", "s2", "s3"],
            },
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute(
            "select state from work.regions where instance_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], "joined")
        cur = await self.conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        before = (await cur.fetchone())[0]
        await self.conn.execute(
            "update work.instances set state = 'shortlisting', attributes = %s where id = %s",
            (json.dumps({"brief_version": 99}), inst),
        )
        from aos.kernel import regions as region_ops
        from aos.registry.kinds import WorkflowDefinition

        defs = await workflow._load_definitions(self.conn, self.pack_version_id)
        wdoc = defs["WorkflowDefinition"][WORKFLOW]
        definition = WorkflowDefinition.model_validate(wdoc)
        attrs = {"brief_version": 99}
        await region_ops.rerun_stale_regions(
            self.conn,
            inst,
            "shortlisting",
            definition,
            attrs,
            packs_dir=self.packs_dir,
            org_id=ORG_ID,
            seat_name=SEAT,
            seat_version=1,
            workflow_name=WORKFLOW,
            pack_name="procurement_demo",
            pack_version=1,
            pack_digest="x",
            defs=defs,
            seat_doc=defs.get("Seat", {}).get(SEAT) or {},
            seat_limits={},
            participants=[("requester", "faisal"), ("buyer", "noura")],
        )
        cur = await self.conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], before)

    async def test_c09_stale_brief_reruns_lookup_before_shortlist(self) -> None:
        inst = "QQ-J09"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _insert_request_intake_done(self.conn, inst)
        await _save_brief_draft(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            content=_brief_content(),
        )
        cur = await self.conn.execute(
            "select id, latest_version from work.artifacts where instance_id = %s and artifact_type = 'brief'",
            (inst,),
        )
        brief_id, brief_ver = await cur.fetchone()
        await artifacts.create_artifact_version(
            self.conn,
            ORG,
            ORG_ID,
            brief_id,
            "faisal",
            {"base_version": int(brief_ver), "content": _brief_v(2)},
            packs_dir=self.packs_dir,
        )
        task_id = await _latest_lookup_task(self.conn, inst)
        contract = await self._build_lookup_contract(self.conn, inst, task_id)
        attempt_id, fencing_token = await _claim_and_admit_lookup(
            self.conn, instance_id=inst, task_id=task_id, contract=contract
        )
        cur = await self.conn.execute(
            "select started_with from work.regions where instance_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0].get("brief_version"), 2)
        saved = await _save_supplier_list_for_attempt(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        await _submit_lookup_pass(
            self.conn,
            attempt_id=attempt_id,
            task_id=task_id,
            contract=contract,
            output_ref={
                "artifact_id": saved["artifact_id"],
                "version": saved["version"],
                "content_hash": saved["content_hash"],
            },
            packs_dir=self.packs_dir,
            fencing_token=fencing_token,
        )
        cur = await self.conn.execute(
            "select started_with, state from work.regions where instance_id = %s",
            (inst,),
        )
        sw, rstate = await cur.fetchone()
        self.assertEqual(rstate, "done")
        self.assertEqual(sw.get("brief_version"), 2)

        await artifacts.create_artifact_version(
            self.conn,
            ORG,
            ORG_ID,
            brief_id,
            "faisal",
            {"base_version": 2, "content": _brief_v(3)},
            packs_dir=self.packs_dir,
        )
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select id from work.pending_items where instance_id = %s and event = %s and status = 'open'",
            (inst, "decision.brief_confirmed"),
        )
        brief_pending = await cur.fetchone()
        self.assertIsNotNone(brief_pending, "brief decision should open after ranking completes")
        await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            brief_pending[0],
            "faisal",
            {"value": "confirm", "expected_version": 1, "artifact_version": 3},
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute("select state, attributes from work.instances where id = %s", (inst,))
        st, attrs_raw = await cur.fetchone()
        self.assertEqual(st, "shortlisting")
        attrs = attrs_raw if isinstance(attrs_raw, dict) else json.loads(attrs_raw)
        self.assertEqual(attrs["brief_version"], 3)
        cur = await self.conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 2)
        cur = await self.conn.execute(
            "select state, started_with from work.regions where instance_id = %s",
            (inst,),
        )
        rstate, sw2 = await cur.fetchone()
        self.assertEqual(rstate, "running")
        self.assertEqual(sw2, {})
        cur = await self.conn.execute(
            "select count(*) from work.pending_items where instance_id = %s and status = 'open'"
            " and event = 'decision.shortlist_confirmed'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 0)

        task2 = await _latest_lookup_task(self.conn, inst)
        self.assertNotEqual(task2, task_id)
        contract2 = await self._build_lookup_contract(self.conn, inst, task2)
        attempt2, fencing2 = await _claim_and_admit_lookup(
            self.conn, instance_id=inst, task_id=task2, contract=contract2
        )
        cur = await self.conn.execute(
            "select started_with from work.regions where instance_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0].get("brief_version"), 3)
        saved2 = await _save_supplier_list_for_attempt(
            self.conn,
            instance_id=inst,
            pack_version_id=self.pack_version_id,
            packs_dir=self.packs_dir,
            task_id=task2,
            attempt_id=attempt2,
        )
        await _submit_lookup_pass(
            self.conn,
            attempt_id=attempt2,
            task_id=task2,
            contract=contract2,
            output_ref={
                "artifact_id": saved2["artifact_id"],
                "version": saved2["version"],
                "content_hash": saved2["content_hash"],
            },
            packs_dir=self.packs_dir,
            fencing_token=fencing2,
        )
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select count(*) from work.pending_items where instance_id = %s and status = 'open'"
            " and event = 'decision.shortlist_confirmed'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 1)

    async def _c03_setup(self, inst: str) -> tuple[str, str, dict, str, int, dict]:
        async def _setup(conn) -> tuple[str, str, dict, str, int, dict]:
            await _insert_instance(conn, instance_id=inst, pack_version_id=self.pack_version_id)
            await _insert_request_intake_done(conn, inst)
            await _save_brief_draft(
                conn,
                instance_id=inst,
                pack_version_id=self.pack_version_id,
                packs_dir=self.packs_dir,
                content=_brief_content(),
            )
            task_id = await _latest_lookup_task(conn, inst)
            defs = await workflow._load_definitions(conn, self.pack_version_id)
            pack_cur = await conn.execute(
                "select pack_name, version, digest from registry.pack_versions where id = %s",
                (self.pack_version_id,),
            )
            pn, pv, pd = await pack_cur.fetchone()
            seat_doc = defs.get("Seat", {}).get(SEAT) or {}
            from aos.kernel import contracts

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
                    "template": "supplier_lookup",
                    "skill": "supplier_lookup",
                    "work_type": "analysis",
                    "verifier": "sources_cited",
                    "on_behalf_of": "buyer",
                },
                participant_role="buyer",
                person_id="noura",
                seat_limits=(seat_doc.get("spec") or {}).get("limits") or {},
            )
            attempt_id, fencing_token = await _claim_and_admit_lookup(
                conn, instance_id=inst, task_id=task_id, contract=contract
            )
            saved = await _save_supplier_list_for_attempt(
                conn,
                instance_id=inst,
                pack_version_id=self.pack_version_id,
                packs_dir=self.packs_dir,
                task_id=task_id,
                attempt_id=attempt_id,
            )
            cur = await conn.execute(
                "select id, latest_version from work.artifacts where instance_id = %s and artifact_type = 'brief'",
                (inst,),
            )
            brief_id, _ = await cur.fetchone()
            await artifacts.create_artifact_version(
                conn,
                ORG,
                ORG_ID,
                brief_id,
                "faisal",
                {"base_version": 1, "content": _brief_v(2)},
                packs_dir=self.packs_dir,
            )
            await artifacts.create_artifact_version(
                conn,
                ORG,
                ORG_ID,
                brief_id,
                "faisal",
                {"base_version": 2, "content": _brief_v(3)},
                packs_dir=self.packs_dir,
            )
            opened = await decisions.open_ready_decisions(conn, inst, org=ORG, packs_dir=self.packs_dir)
            if not opened:
                cur = await conn.execute(
                    "select id from work.pending_items where instance_id = %s and event = %s and status = 'open'",
                    (inst, "decision.brief_confirmed"),
                )
                row = await cur.fetchone()
                pending_id = str(row[0]) if row else None
            else:
                pending_id = opened[0]
            assert pending_id is not None, "brief decision pending must exist before C03 race"
            output_ref = {
                "artifact_id": saved["artifact_id"],
                "version": saved["version"],
                "content_hash": saved["content_hash"],
            }
            return task_id, attempt_id, contract, pending_id, fencing_token, output_ref

        return await _setup(self.conn)

    async def _c03_run(self, inst: str, *, complete_first: bool) -> None:
        url = _pg.kernel_url(self.db)
        (
            task_id,
            attempt_id,
            contract,
            pending_id,
            fencing_token,
            output_ref,
        ) = await self._c03_setup(inst)
        await self.conn.commit()

        async def _complete_lookup() -> None:
            async with await psycopg.AsyncConnection.connect(url) as conn:
                async with conn.transaction():
                    await _submit_lookup_pass(
                        conn,
                        attempt_id=attempt_id,
                        task_id=task_id,
                        contract=contract,
                        output_ref=output_ref,
                        packs_dir=self.packs_dir,
                        fencing_token=fencing_token,
                    )

        async def _confirm_brief() -> None:
            async with await psycopg.AsyncConnection.connect(url) as conn:
                async with conn.transaction():
                    await decisions.decide_pending(
                        conn,
                        ORG,
                        ORG_ID,
                        pending_id,
                        "faisal",
                        {"value": "confirm", "expected_version": 1, "artifact_version": 3},
                        idempotency_key=None,
                        packs_dir=self.packs_dir,
                    )

        if complete_first:
            await _complete_lookup()
            await _confirm_brief()
        else:
            await _confirm_brief()
            await _complete_lookup()

        async with await psycopg.AsyncConnection.connect(url) as conn:
            await self._assert_c03_end_state(conn, inst)

    async def test_c03_concurrent_completion_and_brief_confirm(self) -> None:
        await self._c03_run("QQ-J03A", complete_first=True)
        await self._c03_run("QQ-J03B", complete_first=False)


def _brief_v(n: int) -> dict:
    return {
        "title": f"Brief v{n}",
        "category": "CAT-1",
        "quantity": 2,
        "specification": "spec",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh",
    }


async def _insert_brief_two_versions(conn, instance_id: str) -> str:
    aid = ids.new_artifact_id()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'brief', '', 'Brief', 'draft', 2)",
        (aid, instance_id),
    )
    for v in (1, 2):
        ch = __import__("hashlib").sha256(_canonical_json(_brief_v(v))).hexdigest()
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'person', 'faisal', '[]', '[]')",
            (aid, v, json.dumps(_brief_v(v)), ch),
        )
    return aid


async def _insert_supplier_list_artifact(
    conn, instance_id: str, *, sids: tuple[str, ...] = ("s1",)
) -> str:
    aid = ids.new_artifact_id()
    rows = []
    for i, sid in enumerate(sids, start=1):
        rows.append(
            {
                "rank": i,
                "supplier": f"S{sid}",
                "supplier_id": sid,
                "score": 90.0 - i,
                "sources": [{"receipt_id": "rcpt_1"}],
            }
        )
    content = {"rows": rows}
    ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'supplier_list', '', 'Suppliers', 'draft', 1)",
        (aid, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'attempt', 'att_x', '[]', '[]')",
        (aid, json.dumps(content), ch),
    )
    return aid


if __name__ == "__main__":
    unittest.main()
