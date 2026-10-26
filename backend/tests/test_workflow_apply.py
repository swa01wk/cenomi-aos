"""M2-BE-01: apply_event persistence, effects and pinned workflow versions."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from aos.kernel import ids, workflow
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.workflow import WorkflowEffectError
from aos.registry.loader import parse_yaml

from . import _pg

REPO = Path(__file__).resolve().parents[2]
ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
PACKS = REPO / "packs"
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


async def _sync_published(conn, packs_dir: Path, *, newer: bool = False) -> str:
    """Sync and publish the pack; ``newer`` publishes the next version with a stricter shortlist guard."""
    root = packs_dir / "procurement_demo"
    if newer:
        pack_yaml = root / "pack.yaml"
        version = int(parse_yaml(pack_yaml.read_text())["metadata"]["version"]) + 1
        lines = pack_yaml.read_text().splitlines()
        pack_yaml.write_text(
            "\n".join(
                f"metadata: {{name: procurement_demo, version: {version}, owner: head_of_procurement}}"
                if line.startswith("metadata:") and "procurement_demo" in line
                else line
                for line in lines
            )
            + "\n"
        )
        wf = root / "workflows" / "quick_quote.yaml"
        wf.write_text(
            wf.read_text().replace(
                'guard: "attr.shortlist_count >= 3"',
                'guard: "attr.shortlist_count >= 5"',
                1,
            )
        )
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
    version: int = 1,
    attributes: dict | None = None,
) -> None:
    attrs = attributes or {}
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
          attributes, created_by, correlation_id
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, %s, %s, 'faisal', 'corr_test')
        """,
        (instance_id, ORG_ID, WORKFLOW, pack_version_id, SEAT, state, version, json.dumps(attrs)),
    )
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, 'requester', 'faisal', 'creation'), (%s, 'buyer', 'noura', 'claim')",
        (instance_id, instance_id),
    )


async def _discovery_join_ready(
    conn, instance_id: str, *, brief_version: int = 1
) -> None:
    await conn.execute(
        """
        insert into work.regions (
          instance_id, name, state, started_on, join_at, join_guard, started_with
        ) values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)', %s)
        on conflict (instance_id, name) do update set state = 'done', started_with = excluded.started_with
        """,
        (instance_id, json.dumps({"brief_version": brief_version})),
    )


async def _apply(conn, instance_id: str, event: str, *, by_role: str | None, packs_dir: Path, **kw):
    return await workflow.apply_event(
        conn,
        instance_id,
        event,
        by_role=by_role,
        packs_dir=packs_dir,
        org=ORG,
        **kw,
    )


@unittest.skipUnless(_pg.available(), "needs a local Postgres")
class WorkflowApplyTests(unittest.IsolatedAsyncioTestCase):
    packs_dir: Path
    v1_id: str

    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.url = _pg.kernel_url(self.db)
        self.packs_dir = PACKS
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            await conn.execute(seed_sql(ORG))
            async with conn.transaction():
                self.v1_id = await _sync_published(conn, self.packs_dir)

    async def asyncTearDown(self) -> None:
        _pg.drop(self.db)

    async def _instance_row(self, instance_id: str) -> dict:
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute(
                    "select state, version, status, closed_at from work.instances where id = %s",
                    (instance_id,),
                )
            ).fetchone()
            assert row is not None
            return row

    async def _task_templates(self, instance_id: str) -> list[str]:
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    "select template from work.tasks where instance_id = %s and kind = 'task' order by template",
                    (instance_id,),
                )
            ).fetchall()
            return [r["template"] for r in rows]

    async def _transition_count(self, instance_id: str) -> int:
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            row = await (
                await conn.execute(
                    "select count(*) from work.instance_transitions where instance_id = %s",
                    (instance_id,),
                )
            ).fetchone()
            return int(row[0])

    async def test_quick_quote_transitions_and_tasks(self) -> None:
        inst = "QQ-9001"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.v1_id)
                steps = [
                    ("decision.brief_confirmed", "requester", {"shortlist_count": 3, "brief_version": 1}),
                    ("decision.shortlist_confirmed", "buyer", {"shortlist_count": 3, "brief_version": 1}),
                    ("task.completed.rfq_draft", None, {"shortlist_count": 3}),
                    ("task.completed.rfq_send", None, {"shortlist_count": 3}),
                    ("timer.quotes_closed", None, {"shortlist_count": 3, "quote_count": 2}),
                    ("decision.supplier_selected", "buyer", {"shortlist_count": 3, "quote_count": 2}),
                    ("task.completed.po_create", None, {"shortlist_count": 3, "quote_count": 2}),
                ]
                attrs = {"shortlist_count": 3}
                for event, role, attr_patch in steps:
                    await conn.execute(
                        "update work.instances set attributes = %s where id = %s",
                        (json.dumps({**attrs, **attr_patch}), inst),
                    )
                    if event == "decision.shortlist_confirmed":
                        await _discovery_join_ready(
                            conn, inst, brief_version=attr_patch.get("brief_version", 1)
                        )
                    if event == "decision.supplier_selected":
                        await conn.execute(
                            """
                            insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)
                            values ('art_cmp', %s, 'comparison', 'default', 'Comparison', 'final', 1)
                            """,
                            (inst,),
                        )
                        await conn.execute(
                            """
                            insert into work.artifact_versions (
                              artifact_id, version, content, content_hash,
                              produced_by_kind, produced_by, inputs, sources
                            ) values ('art_cmp', 1, '{}', 'abc', 'person', 'noura', '[]', '[]')
                            """
                        )
                    r = await _apply(conn, inst, event, by_role=role, packs_dir=self.packs_dir)
                    self.assertTrue(r.applied, event)
                    attrs = {**attrs, **attr_patch}

        self.assertEqual(await self._transition_count(inst), 7)
        self.assertEqual(
            await self._task_templates(inst),
            ["po_create", "quote_comparison", "rfq_draft", "rfq_send"],
        )
        row = await self._instance_row(inst)
        self.assertEqual(row["state"], "closed")
        self.assertEqual(row["version"], 8)
        self.assertEqual(row["status"], "closed")
        self.assertIsNotNone(row["closed_at"])

        inst_stream = ids.stream_instance(inst)
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            ob = await (
                await conn.execute(
                    "select stream, count(*) as c from evidence.outbox"
                    " where instance_id = %s and event_type = 'instance.state_changed'"
                    " group by stream order by stream",
                    (inst,),
                )
            ).fetchall()
            ob_map = {r["stream"]: int(r["c"]) for r in ob}
            self.assertEqual(ob_map[inst_stream], 7)
            self.assertEqual(ob_map[ids.stream_user("faisal")], 7)
            self.assertEqual(ob_map[ids.stream_user("noura")], 7)

            ev_count = await (
                await conn.execute(
                    "select count(*) as c from evidence.execution_events"
                    " where run_id = %s and event_type = 'StateTransitioned'",
                    (inst,),
                )
            ).fetchone()
            self.assertEqual(int(ev_count["c"]), 7)

            timer = await (
                await conn.execute(
                    "select status from work.timers where instance_id = %s and name = 'quote_deadline'",
                    (inst,),
                )
            ).fetchone()
            self.assertIsNotNone(timer)
            self.assertEqual(timer["status"], "cancelled")

            art = await (
                await conn.execute("select status from work.artifacts where id = 'art_cmp'")
            ).fetchone()
            self.assertEqual(art["status"], "locked")

            ntf = await (
                await conn.execute(
                    "select person_id from work.notifications where instance_id = %s",
                    (inst,),
                )
            ).fetchone()
            self.assertEqual(ntf["person_id"], "faisal")

    async def test_event_after_close_is_not_running(self) -> None:
        inst = "QQ-9006"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.v1_id,
                    state="closed",
                    version=8,
                )
                await conn.execute(
                    "update work.instances set status = 'closed', closed_at = now() where id = %s",
                    (inst,),
                )
                r = await _apply(
                    conn, inst, "decision.brief_confirmed", by_role="requester", packs_dir=self.packs_dir
                )
        self.assertFalse(r.applied)
        self.assertEqual(r.reason, "not_running")
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            ev = await (
                await conn.execute(
                    "select attributes from evidence.execution_events where run_id = %s",
                    (inst,),
                )
            ).fetchone()
            self.assertEqual(ev["attributes"]["reason"], "not_running")

    async def test_apply_event_rejects_unknown_actor_kind(self) -> None:
        inst = "QQ-9007"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.v1_id)
                with self.assertRaises(ValueError):
                    await _apply(
                        conn,
                        inst,
                        "decision.brief_confirmed",
                        by_role="requester",
                        packs_dir=self.packs_dir,
                        actor={"kind": "unknown", "id": "x"},
                    )

    async def test_wrong_role_refused(self) -> None:
        inst = "QQ-9002"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.v1_id)
                r = await _apply(
                    conn, inst, "decision.brief_confirmed", by_role="buyer", packs_dir=self.packs_dir
                )
        self.assertFalse(r.applied)
        self.assertEqual(r.reason, "wrong_role")
        row = await self._instance_row(inst)
        self.assertEqual(row["state"], "intake")
        self.assertEqual(row["version"], 1)
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            ev = await (
                await conn.execute(
                    "select event_type, attributes from evidence.execution_events where run_id = %s",
                    (inst,),
                )
            ).fetchone()
            self.assertEqual(ev["event_type"], "WorkflowEventIgnored")
            self.assertEqual(ev["attributes"]["reason"], "wrong_role")

    async def test_guard_failed_state_unchanged(self) -> None:
        inst = "QQ-9003"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.v1_id,
                    state="shortlisting",
                    attributes={"shortlist_count": 2},
                )
                r = await _apply(
                    conn, inst, "decision.shortlist_confirmed", by_role="buyer", packs_dir=self.packs_dir
                )
        self.assertFalse(r.applied)
        self.assertEqual(r.reason, "guard_failed")
        self.assertEqual(await self._transition_count(inst), 0)
        row = await self._instance_row(inst)
        self.assertEqual(row["state"], "shortlisting")

    async def test_broken_lock_effect_rolls_back(self) -> None:
        inst = "QQ-9004"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            await _insert_instance(
                conn,
                instance_id=inst,
                pack_version_id=self.v1_id,
                state="comparison",
                version=6,
                attributes={"shortlist_count": 3, "quote_count": 2},
            )
            with self.assertRaises(WorkflowEffectError):
                async with conn.transaction():
                    await _apply(
                        conn,
                        inst,
                        "decision.supplier_selected",
                        by_role="buyer",
                        packs_dir=self.packs_dir,
                    )
        row = await self._instance_row(inst)
        self.assertEqual(row["state"], "comparison")
        self.assertEqual(row["version"], 6)
        self.assertEqual(await self._transition_count(inst), 0)

    async def test_c12_pinned_v1_after_v2_published(self) -> None:
        inst = "QQ-9005"
        tmp = Path(tempfile.mkdtemp(prefix="aos-pack-v2-"))
        try:
            shutil.copytree(PACKS / "procurement_demo", tmp / "procurement_demo")
            async with await psycopg.AsyncConnection.connect(self.url) as conn:
                async with conn.transaction():
                    v2_id = await _sync_published(conn, tmp, newer=True)
                    self.assertNotEqual(v2_id, self.v1_id)
                    await _insert_instance(
                        conn,
                        instance_id=inst,
                        pack_version_id=self.v1_id,
                        state="shortlisting",
                        attributes={"shortlist_count": 3, "brief_version": 1},
                    )
                    await _discovery_join_ready(conn, inst, brief_version=1)
                    r = await _apply(
                        conn,
                        inst,
                        "decision.shortlist_confirmed",
                        by_role="buyer",
                        packs_dir=self.packs_dir,
                    )
            self.assertTrue(r.applied)
            self.assertEqual(r.to_state, "rfq_drafting")
            self.assertEqual(await self._task_templates(inst), ["rfq_draft"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
