"""M2-BE-03: queue, claim and by-rule participant binding."""

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
from aos.kernel import ids, instances, participants
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import OrgModel, Person, load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"
QUEUE = "procurement/sourcing"


def _org_two_sourcing_claimants() -> OrgModel:
    data = ORG.model_dump()
    data["people"]["sourcing_b"] = Person(
        name="Sourcing B",
        team=QUEUE,
        roles=["sourcing_user"],
        console=False,
    )
    return OrgModel.model_validate(data)


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
    with_buyer: bool = False,
) -> None:
    attrs = attributes or {}
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
          attributes, created_by, correlation_id
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, %s, %s, 'faisal', %s)
        """,
        (
            instance_id,
            ORG_ID,
            WORKFLOW,
            pack_version_id,
            SEAT,
            state,
            version,
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


def _brief_v(n: int) -> dict:
    return {
        "title": f"Brief v{n}",
        "category": "CAT-1",
        "quantity": 2,
        "specification": "spec",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh",
    }


async def _insert_brief(conn, instance_id: str, versions: list[dict]) -> None:
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
            " values (%s, %s, %s, %s, 'attempt', 'att_x', '[]', '[]')",
            (aid, i, json.dumps(content), ch),
        )


async def _insert_supplier_list(conn, instance_id: str, *, sids: tuple[str, ...] = ("s1", "s2", "s3")) -> None:
    from tests.test_decisions import _insert_supplier_list as _isl

    await _isl(conn, instance_id, sids=sids)


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


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ParticipantsKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.url = _pg.kernel_url(self.db)
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-part-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.org = _org_two_sourcing_claimants()
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            await conn.execute(seed_sql(self.org))
            async with conn.transaction():
                self.pack_version_id = await _sync_published(conn, self.packs_dir)

    async def asyncTearDown(self) -> None:
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_concurrent_claims_one_wins(self) -> None:
        inst = "QQ-P01"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.pack_version_id)

        async def _claim(person_id: str) -> None:
            async with await psycopg.AsyncConnection.connect(self.url) as c:
                async with c.transaction():
                    await participants.claim_instance(
                        c,
                        self.org,
                        ORG_ID,
                        person_id,
                        inst,
                        "buyer",
                        1,
                        packs_dir=self.packs_dir,
                    )

        async def _claim_or_fail(person_id: str) -> str | None:
            try:
                await _claim(person_id)
                return None
            except participants.ParticipantError as exc:
                return exc.code

        results = await asyncio.gather(_claim_or_fail("noura"), _claim_or_fail("sourcing_b"))
        codes = [c for c in results if c is not None]
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0], "already_claimed")
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            cur = await conn.execute(
                "select count(*) from work.participants where instance_id = %s and role = 'buyer'",
                (inst,),
            )
            self.assertEqual((await cur.fetchone())[0], 1)

    async def test_queue_only_for_queue_team(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            items = await participants.list_queue_instances(conn, self.org, ORG_ID, "noura", QUEUE)
            self.assertIsInstance(items, list)
            with self.assertRaises(participants.ParticipantError) as ctx:
                await participants.list_queue_instances(conn, self.org, ORG_ID, "faisal", QUEUE)
            self.assertEqual(ctx.exception.status, 403)

    async def test_intake_job_in_queue_until_claimed(self) -> None:
        inst = "QQ-P02"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.pack_version_id)
            items = await participants.list_queue_instances(conn, self.org, ORG_ID, "noura", QUEUE)
            self.assertEqual({i["instance_id"] for i in items}, {inst})
            self.assertEqual(items[0]["waiting_on"]["kind"], "queue")
            self.assertEqual(items[0]["waiting_on"]["label"], "Sourcing")
            self.assertIsNone(items[0]["requester"])
            self.assertIsNone(items[0]["buyer"])
            async with conn.transaction():
                await participants.claim_instance(
                    conn,
                    self.org,
                    ORG_ID,
                    "noura",
                    inst,
                    "buyer",
                    1,
                    packs_dir=self.packs_dir,
                )
            items_after = await participants.list_queue_instances(conn, self.org, ORG_ID, "noura", QUEUE)
            self.assertEqual(items_after, [])

    async def test_requester_cannot_claim(self) -> None:
        inst = "QQ-P03"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.pack_version_id)
            with self.assertRaises(participants.ParticipantError) as ctx:
                async with conn.transaction():
                    await participants.claim_instance(
                        conn,
                        self.org,
                        ORG_ID,
                        "faisal",
                        inst,
                        "buyer",
                        1,
                        packs_dir=self.packs_dir,
                    )
            self.assertEqual(ctx.exception.status, 403)

    async def test_stale_version_on_claim(self) -> None:
        inst = "QQ-P04"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn, instance_id=inst, pack_version_id=self.pack_version_id, version=2
                )
            with self.assertRaises(participants.ParticipantError) as ctx:
                async with conn.transaction():
                    await participants.claim_instance(
                        conn,
                        self.org,
                        ORG_ID,
                        "noura",
                        inst,
                        "buyer",
                        1,
                        packs_dir=self.packs_dir,
                    )
            self.assertEqual(ctx.exception.code, "stale_version")

    async def test_claim_opens_shortlist_pending_in_snapshot(self) -> None:
        inst = "QQ-P05"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.pack_version_id,
                    state="shortlisting",
                    version=2,
                    attributes={"brief_version": 1},
                )
                await _insert_supplier_list(conn, inst)
                await _region_done(conn, inst)
            async with conn.transaction():
                snap = await participants.claim_instance(
                    conn,
                    self.org,
                    ORG_ID,
                    "noura",
                    inst,
                    "buyer",
                    2,
                    packs_dir=self.packs_dir,
                )
            self.assertEqual(len(snap["pending"]), 1)
            self.assertEqual(snap["pending"][0]["event"], "decision.shortlist_confirmed")
            self.assertEqual(snap["pending"][0]["for_person_id"], "noura")
            snap_faisal = await instances.build_snapshot(conn, self.org, ORG_ID, inst, "faisal")
            self.assertEqual(snap_faisal["pending"], [])
            cur = await conn.execute(
                "select blocks from work.turns where instance_id = %s and author_kind = 'seat'"
                " and blocks::text like '%%pending_ref%%' order by seq desc limit 1",
                (inst,),
            )
            row = await cur.fetchone()
            self.assertIsNotNone(row)

    async def test_by_rule_binds_on_first_need(self) -> None:
        inst = "QQ-P06"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.pack_version_id)
            cur = await conn.execute(
                "select count(*) from work.participants where instance_id = %s and role = 'procurement_approver'",
                (inst,),
            )
            self.assertEqual((await cur.fetchone())[0], 0)
            with self.assertRaises(instances.InstanceError):
                await instances.build_snapshot(conn, self.org, ORG_ID, inst, "khalid")
            async with conn.transaction():
                pid1 = await participants.resolve_participant(
                    conn, self.org, inst, "procurement_approver"
                )
            self.assertEqual(pid1, "khalid")
            cur = await conn.execute(
                "select bound_by from work.participants where instance_id = %s and role = 'procurement_approver'",
                (inst,),
            )
            self.assertEqual((await cur.fetchone())[0], "rule")
            async with conn.transaction():
                pid2 = await participants.resolve_participant(
                    conn, self.org, inst, "procurement_approver"
                )
            self.assertEqual(pid2, "khalid")
            cur = await conn.execute(
                "select count(*) from work.participants where instance_id = %s and role = 'procurement_approver'",
                (inst,),
            )
            self.assertEqual((await cur.fetchone())[0], 1)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ParticipantsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-part-api-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs_dir / "procurement_demo")
        cls.org = _org_two_sourcing_claimants()

        async def _seed() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(cls.db)) as conn:
                await conn.execute(seed_sql(cls.org))
                async with conn.transaction():
                    cls.pack_version_id = await _sync_published(conn, cls.packs_dir)

        asyncio.run(_seed())
        settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs_dir,
            seed_on_start=False,
            session_secret="test-secret-" + "x" * 40,
        )
        cls.client = TestClient(create_app(settings))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs_dir, ignore_errors=True)

    def _token(self, person: str) -> str:
        return self.client.post("/api/auth/session", json={"person_id": person}).json()["token"]

    def test_list_queue_http(self) -> None:
        h = {"Authorization": "Bearer " + self._token("noura")}
        r = self.client.get(f"/api/queues/{QUEUE}/instances", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("items", r.json())
