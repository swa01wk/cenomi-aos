"""M2-BE-04: kernel decisions, decidePending, createArtifactVersion."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from aos.api import create_app
from aos.kernel import artifacts, decisions, ids, workflow
from aos.kernel.worker_fence import ClaimedAttempt
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

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
    version: int = 1,
    attributes: dict | None = None,
    with_buyer: bool = True,
) -> None:
    attrs = attributes or {}
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
          attributes, created_by, correlation_id
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, %s, %s, 'faisal', %s)
        """,
        (instance_id, ORG_ID, WORKFLOW, pack_version_id, SEAT, state, version, json.dumps(attrs), f"corr_{instance_id}"),
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


async def _insert_task_completed(conn, instance_id: str, template: str) -> None:
    tid = ids.new_task_id()
    await conn.execute(
        """
        insert into work.tasks (
          id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
        ) values (%s, %s, 'task', %s, %s, 'analysis', 'COMPLETED', '{}', 'hash', 3)
        """,
        (tid, instance_id, template, template),
    )


async def _insert_brief(conn, instance_id: str, versions: list[dict]) -> str:
    aid = ids.new_artifact_id()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'brief', '', 'Brief', 'draft', %s)",
        (aid, instance_id, len(versions)),
    )
    for i, content in enumerate(versions, start=1):
        ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'person', 'faisal', '[]', '[]')",
            (aid, i, json.dumps(content), ch),
        )
    return aid


def _supplier_content(sids: tuple[str, ...]) -> dict:
    return {
        "rows": [
            {
                "rank": i + 1,
                "supplier": f"Supplier {sid}",
                "supplier_id": sid,
                "score": 1.0,
                "sources": [],
            }
            for i, sid in enumerate(sids)
        ]
    }


async def _insert_supplier_list(
    conn,
    instance_id: str,
    *,
    sids: tuple[str, ...] = ("s1",),
    version_contents: list[dict] | None = None,
) -> str:
    contents = version_contents or [_supplier_content(sids)]
    aid = ids.new_artifact_id()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'supplier_list', '', 'Suppliers', 'draft', %s)",
        (aid, instance_id, len(contents)),
    )
    for i, content in enumerate(contents, start=1):
        ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'attempt', 'att_x', '[]', '[]')",
            (aid, i, json.dumps(content), ch),
        )
    return aid


async def _region_done(conn, instance_id: str, *, brief_version: int = 1) -> None:
    await conn.execute(
        """
        insert into work.regions (
          instance_id, name, state, started_on, join_at, join_guard, started_with
        ) values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)', %s)
        """,
        (instance_id, json.dumps({"brief_version": brief_version})),
    )
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    attrs = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    attrs["brief_version"] = brief_version
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (json.dumps(attrs), instance_id),
    )


def _brief_v(n: int) -> dict:
    return {
        "title": f"Brief v{n}",
        "category": "CAT-1",
        "quantity": 2,
        "specification": "spec",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh",
    }


@unittest.skipUnless(_pg.available(), "no local Postgres")
class DecisionsKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-dec-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_open_ready_idempotent(self) -> None:
        inst = "QQ-D01"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _insert_task_completed(self.conn, inst, "request_intake")
        await _insert_brief(self.conn, inst, [_brief_v(1)])
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select count(*) as c from work.pending_items where instance_id = %s and status = 'open'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 1)

    async def test_open_ready_no_shortlist_without_region_or_buyer(self) -> None:
        inst = "QQ-D02"
        await _insert_instance(
            self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting", with_buyer=False
        )
        await _insert_supplier_list(self.conn, inst)
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select count(*) as c from work.pending_items where instance_id = %s and event = %s",
            (inst, "decision.shortlist_confirmed"),
        )
        self.assertEqual((await cur.fetchone())[0], 0)
        await self.conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, 'buyer', 'noura', 'claim')",
            (inst,),
        )
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select count(*) as c from work.pending_items where instance_id = %s and event = %s",
            (inst, "decision.shortlist_confirmed"),
        )
        self.assertEqual((await cur.fetchone())[0], 0)
        await _region_done(self.conn, inst)
        await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        cur = await self.conn.execute(
            "select count(*) as c from work.pending_items where instance_id = %s and status = 'open'"
            " and event = 'decision.shortlist_confirmed'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 1)

    async def _open_brief_pending(self, inst: str) -> str:
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _insert_task_completed(self.conn, inst, "request_intake")
        await _insert_brief(self.conn, inst, [_brief_v(1), _brief_v(2)])
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        self.assertEqual(len(opened), 1)
        return opened[0]

    async def test_decide_brief_moves_state_and_sets_attribute(self) -> None:
        inst = "QQ-D03"
        pending_id = await self._open_brief_pending(inst)
        rec = await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            pending_id,
            "faisal",
            {"value": "confirm", "expected_version": 1, "artifact_version": 2},
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        self.assertEqual(rec["resulting_state"], "shortlisting")
        cur = await self.conn.execute("select state, attributes from work.instances where id = %s", (inst,))
        row = await cur.fetchone()
        self.assertEqual(row[0], "shortlisting")
        attrs = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        self.assertEqual(attrs["brief_version"], 2)
        cur = await self.conn.execute("select status from work.artifacts where instance_id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], "final")

    async def test_stale_artifact_version_409(self) -> None:
        inst = "QQ-D04"
        pending_id = await self._open_brief_pending(inst)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "faisal",
                {"value": "confirm", "expected_version": 1, "artifact_version": 1},
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "stale_version")

    async def test_wrong_participant_403(self) -> None:
        inst = "QQ-D05"
        pending_id = await self._open_brief_pending(inst)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "noura",
                {"value": "confirm", "expected_version": 1, "artifact_version": 2},
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "not_permitted")

    async def test_idempotency_c01(self) -> None:
        inst = "QQ-D06"
        pending_id = await self._open_brief_pending(inst)
        body = {"value": "confirm", "expected_version": 1, "artifact_version": 2, "note": None}
        key = "idem-brief-1"
        r1 = await decisions.decide_pending(
            self.conn, ORG, ORG_ID, pending_id, "faisal", body, idempotency_key=key, packs_dir=self.packs_dir
        )
        cur = await self.conn.execute("select count(*) as c from gov.decision_records where idempotency_key = %s", (key,))
        self.assertEqual((await cur.fetchone())[0], 1)
        inst2 = "QQ-D06B"
        pending_id2 = await self._open_brief_pending(inst2)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
                self.conn,
                ORG,
                ORG_ID,
                pending_id2,
                "faisal",
                {**body, "expected_version": 1},
                idempotency_key=key,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "validation_failed")
        r2 = await decisions.decide_pending(
            self.conn, ORG, ORG_ID, pending_id, "faisal", body, idempotency_key=key, packs_dir=self.packs_dir
        )
        self.assertEqual(r1, r2)
        cur = await self.conn.execute("select count(*) as c from gov.decision_records where idempotency_key = %s", (key,))
        self.assertEqual((await cur.fetchone())[0], 1)

    async def test_resolved_pending_409(self) -> None:
        inst = "QQ-D07"
        pending_id = await self._open_brief_pending(inst)
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
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "faisal",
                {"value": "confirm", "expected_version": 2, "artifact_version": 2},
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "conflict")

    async def test_shortlist_guard_reopens_pending(self) -> None:
        inst = "QQ-D08"
        await _insert_instance(
            self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting", version=2
        )
        await _insert_supplier_list(self.conn, inst, sids=("s1", "s2", "s3"))
        await _region_done(self.conn, inst)
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        pending_id = opened[0]
        rec = await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            pending_id,
            "noura",
            {"value": "confirm", "expected_version": 2, "artifact_version": 1, "selection": ["s1", "s2"]},
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        self.assertEqual(rec["resulting_state"], "shortlisting")
        cur = await self.conn.execute("select attributes from work.instances where id = %s", (inst,))
        attrs = (await cur.fetchone())[0]
        attrs = attrs if isinstance(attrs, dict) else json.loads(attrs)
        self.assertEqual(attrs["shortlist_count"], 2)
        cur = await self.conn.execute(
            "select count(*) as c from work.pending_items where instance_id = %s and event = %s and status = 'open'",
            (inst, "decision.shortlist_confirmed"),
        )
        self.assertEqual((await cur.fetchone())[0], 1)
        cur = await self.conn.execute(
            "select id from work.pending_items where instance_id = %s and event = %s and status = 'open'",
            (inst, "decision.shortlist_confirmed"),
        )
        pending2 = (await cur.fetchone())[0]
        rec2 = await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            pending2,
            "noura",
            {
                "value": "confirm",
                "expected_version": 2,
                "artifact_version": 1,
                "selection": ["s1", "s2", "s3"],
            },
            idempotency_key=None,
            packs_dir=self.packs_dir,
        )
        self.assertEqual(rec2["resulting_state"], "rfq_drafting")

    async def test_shortlist_stale_artifact_version_409(self) -> None:
        inst = "QQ-D09"
        await _insert_instance(
            self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting", version=2
        )
        v1 = _supplier_content(("s1",))
        v2 = _supplier_content(("s1", "s2"))
        await _insert_supplier_list(self.conn, inst, version_contents=[v1, v2])
        await _region_done(self.conn, inst)
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            opened[0],
                "noura",
                {
                    "value": "confirm",
                    "expected_version": 2,
                    "artifact_version": 1,
                    "selection": ["s1"],
                },
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "stale_version")
        self.assertEqual(ctx.exception.title, "Version changed")

    async def test_shortlist_selection_invalid_ids_422(self) -> None:
        inst = "QQ-D10"
        await _insert_instance(
            self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting", version=2
        )
        await _insert_supplier_list(self.conn, inst, sids=("s1", "s2", "s3"))
        await _region_done(self.conn, inst)
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            opened[0],
                "noura",
                {
                    "value": "confirm",
                    "expected_version": 2,
                    "artifact_version": 1,
                    "selection": ["s1", "s9", "s8"],
                },
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "validation_failed")

    async def test_shortlist_selection_duplicate_422(self) -> None:
        inst = "QQ-D11"
        await _insert_instance(
            self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting", version=2
        )
        await _insert_supplier_list(self.conn, inst, sids=("s1", "s2", "s3"))
        await _region_done(self.conn, inst)
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        with self.assertRaises(decisions.DecisionError) as ctx:
            await decisions.decide_pending(
            self.conn,
            ORG,
            ORG_ID,
            opened[0],
                "noura",
                {
                    "value": "confirm",
                    "expected_version": 2,
                    "artifact_version": 1,
                    "selection": ["s1", "s1", "s2"],
                },
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
        self.assertEqual(ctx.exception.code, "validation_failed")

    async def test_save_draft_voids_confirm_and_reopens(self) -> None:
        inst = "QQ-D12"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        await _insert_task_completed(self.conn, inst, "request_intake")
        aid = await _insert_brief(self.conn, inst, [_brief_v(1), _brief_v(2)])
        opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs_dir)
        pending_id = opened[0]
        defs = await workflow._load_definitions(self.conn, self.pack_version_id)
        gate = ClaimedAttempt(
            attempt_id="att_dec_test",
            task_id=ids.new_task_id(),
            instance_id=inst,
            org_id=ORG_ID,
            seat=SEAT,
            seat_version=1,
            correlation_id=f"corr_{inst}",
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
        await artifacts.save_draft_from_attempt(
            conn=self.conn,
            org=ORG,
            gate=gate,
            body={"artifact_type": "brief", "artifact_id": aid, "base_version": 2, "content": _brief_v(3)},
            defs=defs,
            packs_dir=self.packs_dir,
        )
        cur = await self.conn.execute("select status from work.pending_items where id = %s", (pending_id,))
        self.assertEqual((await cur.fetchone())[0], "voided")
        cur = await self.conn.execute(
            "select artifact_ref->>'version' from work.pending_items"
            " where instance_id = %s and status = 'open'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], "3")


@unittest.skipUnless(_pg.available(), "no local Postgres")
class DecisionsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-dec-api-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
        )
        cls.client = TestClient(create_app(settings))
        cls.client.__enter__()
        cls.loop = asyncio.new_event_loop()
        cls.conn = cls.loop.run_until_complete(psycopg.AsyncConnection.connect(_pg.kernel_url(cls.db)))
        cls.loop.run_until_complete(cls.conn.execute(seed_sql(ORG)))
        cls.pack_version_id = cls.loop.run_until_complete(_sync_published(cls.conn, cls.packs))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.conn.close())
        cls.client.__exit__(None, None, None)
        cls.loop.close()
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    @classmethod
    def _auth(cls, person: str) -> dict:
        token = cls.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_create_version_hidden_fields_403(self) -> None:
        inst = "QQ-DAPI1"

        async def setup() -> str:
            await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting")
            return await _insert_supplier_list(self.conn, inst)

        aid = self.loop.run_until_complete(setup())
        self.loop.run_until_complete(self.conn.commit())
        r = self.client.post(
            f"/api/artifacts/{aid}/versions",
            headers=self._auth("faisal"),
            json={"base_version": 1, "content": {"rows": []}},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_brief_edit_voids_pending_and_reopens(self) -> None:
        inst = "QQ-DAPI2"

        async def setup() -> tuple[str, str]:
            await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
            await _insert_task_completed(self.conn, inst, "request_intake")
            aid = await _insert_brief(self.conn, inst, [_brief_v(1)])
            opened = await decisions.open_ready_decisions(self.conn, inst, org=ORG, packs_dir=self.packs)
            return aid, opened[0]

        aid, pending_id = self.loop.run_until_complete(setup())
        self.loop.run_until_complete(self.conn.commit())
        r = self.client.post(
            f"/api/artifacts/{aid}/versions",
            headers=self._auth("faisal"),
            json={"base_version": 1, "content": _brief_v(2)},
        )
        self.assertEqual(r.status_code, 201)
        cur = self.loop.run_until_complete(
            self.conn.execute("select status from work.pending_items where id = %s", (pending_id,))
        )
        self.assertEqual(self.loop.run_until_complete(cur.fetchone())[0], "voided")
        cur = self.loop.run_until_complete(
            self.conn.execute(
                "select artifact_ref->>'version' as v from work.pending_items"
                " where instance_id = %s and status = 'open'",
                (inst,),
            )
        )
        self.assertEqual(self.loop.run_until_complete(cur.fetchone())[0], "2")

    def test_brief_edit_missing_required_field_422(self) -> None:
        inst = "QQ-DAPI3"

        async def setup() -> str:
            await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
            return await _insert_brief(self.conn, inst, [_brief_v(1)])

        aid = self.loop.run_until_complete(setup())
        self.loop.run_until_complete(self.conn.commit())
        incomplete = dict(_brief_v(2))
        del incomplete["delivery_site"]
        r = self.client.post(
            f"/api/artifacts/{aid}/versions",
            headers=self._auth("faisal"),
            json={"base_version": 1, "content": incomplete},
        )
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "validation_failed")


if __name__ == "__main__":
    unittest.main()
