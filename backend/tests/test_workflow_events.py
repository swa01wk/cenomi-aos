"""M2-BE-02 part 1: pack event triggers, raise_event, parallel region start and finish."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg

from aos.kernel import artifacts, decisions, events, ids, workflow
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
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
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
            values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
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


if __name__ == "__main__":
    unittest.main()
