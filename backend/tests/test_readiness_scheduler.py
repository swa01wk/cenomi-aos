"""M2-BE-05 part 2: readiness tick, task.retry, scheduler exception progress."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg

from aos.kernel import decisions, ids, readiness, workflow
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO
from aos.kernel.task_retry import decide_task_retry, open_task_retry_pending
from aos.kernel.worker_attempts import expire_one_attempt

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
) -> None:
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
          attributes, created_by, correlation_id, status
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, %s, '{}', 'faisal', %s, 'running')
        """,
        (instance_id, ORG_ID, WORKFLOW, pack_version_id, SEAT, state, version, f"corr_{instance_id}"),
    )
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, 'requester', 'faisal', 'creation'), (%s, 'buyer', 'noura', 'claim')",
        (instance_id, instance_id),
    )


async def _minimal_task_contract(
    conn,
    pack_version_id: str,
    task_id: str,
    instance_id: str,
    packs_dir: Path,
    *,
    template: str = "request_intake",
    skill: str | None = None,
    verifier: str | None = None,
    on_behalf_of: str = "requester",
    participant_role: str = "requester",
    person_id: str = "faisal",
) -> dict:
    defs = await workflow._load_definitions(conn, pack_version_id)
    pack_cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s",
        (pack_version_id,),
    )
    pn, pv, pd = await pack_cur.fetchone()
    seat_doc = defs.get("Seat", {}).get(SEAT) or {}
    from aos.kernel import contracts

    return contracts.build_task_contract(
        packs_dir=packs_dir,
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
            "template": template,
            "skill": skill or template,
            "work_type": "analysis",
            "verifier": verifier,
            "on_behalf_of": on_behalf_of,
        },
        participant_role=participant_role,
        person_id=person_id,
        seat_limits=(seat_doc.get("spec") or {}).get("limits") or {},
    )


@unittest.skipUnless(_pg.available(), "needs Postgres")
class ReadinessSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-readiness-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await insert_seats_for_published_pack(
            self.conn,
            org=ORG,
            org_id=ORG_ID,
            pack_version_id=self.pack_version_id,
        )
        await self.conn.execute(
            "update registry.seats set state = 'ACTIVE'"
            " where org_id = %s and name = %s and version = 1",
            (ORG_ID, SEAT),
        )
        await self.conn.commit()

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def _insert_created_task(
        self,
        conn,
        *,
        instance_id: str,
        state: str = "intake",
        region: str | None = None,
        set_current: bool = True,
        template: str = "request_intake",
        skill: str | None = None,
        verifier: str | None = None,
        on_behalf_of: str = "requester",
    ) -> str:
        await _insert_instance(conn, instance_id=instance_id, pack_version_id=self.pack_version_id, state=state)
        task_id = ids.new_task_id()
        contract = await _minimal_task_contract(
            conn,
            self.pack_version_id,
            task_id,
            instance_id,
            self.packs_dir,
            template=template,
            skill=skill,
            verifier=verifier,
            on_behalf_of=on_behalf_of,
            participant_role=on_behalf_of,
            person_id="faisal" if on_behalf_of == "requester" else "noura",
        )
        skill_name = skill or template
        await conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, region, state,
              contract, contract_hash, max_attempts
            ) values (%s, %s, 'task', %s, %s, 'analysis', %s,
                      %s, 'CREATED', %s, %s, 3)
            """,
            (
                task_id,
                instance_id,
                template,
                skill_name,
                verifier,
                region,
                json.dumps(contract),
                contract["contract_hash"],
            ),
        )
        if region and set_current:
            await conn.execute(
                "update work.regions set current_task = %s where instance_id = %s and name = %s",
                (task_id, instance_id, region),
            )
        return task_id

    async def test_racing_readiness_ticks_admit_one_attempt(self) -> None:
        inst = "QQ-R01"
        task_id = await self._insert_created_task(self.conn, instance_id=inst)
        await self.conn.commit()
        url = _pg.kernel_url(self.db)

        async def _tick() -> None:
            async with await psycopg.AsyncConnection.connect(url) as conn:
                async with conn.transaction():
                    await readiness.process_ready_task(
                        conn, task_id, org=ORG, packs_dir=self.packs_dir
                    )

        await asyncio.gather(_tick(), _tick())
        async with await psycopg.AsyncConnection.connect(url) as verify:
            cur = await verify.execute(
                "select count(*) from work.attempts where task_id = %s",
                (task_id,),
            )
            count = (await cur.fetchone())[0]
            tcur = await verify.execute(
                "select state, waiting_for from work.tasks where id = %s",
                (task_id,),
            )
            task_row = await tcur.fetchone()
        self.assertEqual(count, 1, msg=f"task row={task_row!r}")

    async def test_stale_state_task_cancelled(self) -> None:
        inst = "QQ-R02"
        task_id = await self._insert_created_task(self.conn, instance_id=inst, state="intake")
        await self.conn.execute("update work.instances set state = 'shortlisting' where id = %s", (inst,))
        await self.conn.commit()
        async with self.conn.transaction():
            await readiness.process_ready_task(
                self.conn, task_id, org=ORG, packs_dir=self.packs_dir
            )
        cur = await self.conn.execute("select state from work.tasks where id = %s", (task_id,))
        self.assertEqual((await cur.fetchone())[0], "CANCELLED")

    async def test_region_task_not_current_not_admitted(self) -> None:
        inst = "QQ-R03"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting")
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
        )
        other = ids.new_task_id()
        task_id = ids.new_task_id()
        for tid in (other, task_id):
            c = await _minimal_task_contract(
                self.conn,
                self.pack_version_id,
                tid,
                inst,
                self.packs_dir,
                template="supplier_lookup",
                verifier="sources_cited",
                on_behalf_of="buyer",
                participant_role="buyer",
                person_id="noura",
            )
            await self.conn.execute(
                """
                insert into work.tasks (
                  id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash, max_attempts
                ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'sources_cited', 'discovery', 'CREATED',
                          %s, %s, 3)
                """,
                (tid, inst, json.dumps(c), c["contract_hash"]),
            )
        await self.conn.execute(
            "update work.regions set current_task = %s where instance_id = %s",
            (other, inst),
        )
        await self.conn.commit()
        async with self.conn.transaction():
            await readiness.process_ready_task(
                self.conn, task_id, org=ORG, packs_dir=self.packs_dir
            )
        cur = await self.conn.execute(
            "select state from work.tasks where id = %s",
            (task_id,),
        )
        self.assertEqual((await cur.fetchone())[0], "CREATED")
        acur = await self.conn.execute("select count(*) from work.attempts where task_id = %s", (task_id,))
        self.assertEqual((await acur.fetchone())[0], 0)

    async def test_budget_refusal_and_code_change(self) -> None:
        inst = "QQ-R04"
        task_id = await self._insert_created_task(self.conn, instance_id=inst)
        tcur = await self.conn.execute("select contract from work.tasks where id = %s", (task_id,))
        contract = (await tcur.fetchone())[0]
        if isinstance(contract, str):
            contract = json.loads(contract)
        reservation = float((contract.get("budget") or {}).get("cost_usd") or 0.5)
        await self.conn.execute(
            """
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values (%s, %s, current_date, %s, %s, 0)
            on conflict (org_id, seat, day) do update
            set reserved_usd = excluded.reserved_usd, settled_usd = 0, limit_usd = excluded.limit_usd
            """,
            (ORG_ID, SEAT, reservation, reservation),
        )
        await self.conn.commit()
        for _ in range(3):
            async with self.conn.transaction():
                await readiness.process_ready_task(
                    self.conn, task_id, org=ORG, packs_dir=self.packs_dir
                )
        cur = await self.conn.execute(
            "select count(*) from gov.decision_records where event = 'admission.denied'"
            " and value = 'budget_exhausted' and subject_id = %s",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 1)
        tcur = await self.conn.execute("select state, waiting_for from work.tasks where id = %s", (task_id,))
        state, wf = await tcur.fetchone()
        self.assertEqual(state, "READY")
        self.assertEqual(wf.get("code"), "budget_exhausted")
        await self.conn.execute(
            "update registry.seats set state = 'PAUSED'"
            " where org_id = %s and name = %s and version = 1",
            (ORG_ID, SEAT),
        )
        async with self.conn.transaction():
            await readiness.process_ready_task(
                self.conn, task_id, org=ORG, packs_dir=self.packs_dir
            )
        cur2 = await self.conn.execute(
            "select count(*) from gov.decision_records where event = 'admission.denied' and subject_id = %s",
            (inst,),
        )
        self.assertEqual((await cur2.fetchone())[0], 2)

    async def test_admit_clears_waiting_for(self) -> None:
        inst = "QQ-R05"
        task_id = await self._insert_created_task(self.conn, instance_id=inst)
        await self.conn.execute(
            "update work.tasks set waiting_for = '{\"kind\":\"admission\",\"code\":\"unavailable\"}'::jsonb"
            " where id = %s",
            (task_id,),
        )
        await self.conn.commit()
        async with self.conn.transaction():
            await readiness.process_ready_task(
                self.conn, task_id, org=ORG, packs_dir=self.packs_dir
            )
        cur = await self.conn.execute("select waiting_for, state from work.tasks where id = %s", (task_id,))
        wf, state = await cur.fetchone()
        self.assertIsNone(wf)
        self.assertEqual(state, "RUNNING")

    async def test_expiry_exception_progress_and_retry_pending(self) -> None:
        inst = "QQ-R06"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id)
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()
        contract = await _minimal_task_contract(
            self.conn,
            self.pack_version_id,
            task_id,
            inst,
            self.packs_dir,
            template="request_intake",
            verifier="brief_schema",
        )
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema', 'RUNNING',
                      %s, %s, 2, 0, 2)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        await self.conn.execute(
            """
            insert into work.attempts (
              id, task_id, n, fencing_token, state, reserved_usd, lease_expires_at, worker_id
            ) values (%s, %s, 2, 1, 'CLAIMED', 0.5, now() - interval '1 minute', 'w-exp')
            """,
            (attempt_id, task_id),
        )
        await self.conn.commit()
        async with self.conn.transaction():
            out = await expire_one_attempt(self.conn, attempt_id=attempt_id, org=ORG)
        self.assertTrue(out.expired)
        cur = await self.conn.execute("select state from work.tasks where id = %s", (task_id,))
        self.assertEqual((await cur.fetchone())[0], "EXCEPTION")
        tcur = await self.conn.execute(
            "select count(*) from work.turns where instance_id = %s and author_kind = 'seat'",
            (inst,),
        )
        self.assertEqual((await tcur.fetchone())[0], 1)
        pcur = await self.conn.execute(
            "select count(*) from work.pending_items where task_id = %s and event = 'task.retry' and status = 'open'",
            (task_id,),
        )
        self.assertEqual((await pcur.fetchone())[0], 1)

    async def test_decide_retry_twice_one_replacement_task(self) -> None:
        inst = "QQ-R07"
        await _insert_instance(self.conn, instance_id=inst, pack_version_id=self.pack_version_id, state="shortlisting")
        await self.conn.execute(
            """
            insert into work.regions (instance_id, name, state, started_on, join_at, join_guard, started_with)
            values (%s, 'discovery', 'running', 'event.intent_identified', 'shortlisting', 'same(brief_version)', '{}')
            """,
            (inst,),
        )
        task_id = ids.new_task_id()
        contract = await _minimal_task_contract(
            self.conn,
            self.pack_version_id,
            task_id,
            inst,
            self.packs_dir,
            template="supplier_lookup",
            verifier="sources_cited",
            on_behalf_of="buyer",
            participant_role="buyer",
            person_id="noura",
        )
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash, max_attempts
            ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'sources_cited', 'discovery', 'EXCEPTION',
                      %s, %s, 3)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        await self.conn.execute(
            "update work.regions set current_task = %s where instance_id = %s and name = 'discovery'",
            (task_id, inst),
        )
        pending_id = await open_task_retry_pending(
            self.conn, org=ORG, org_id=ORG_ID, instance_id=inst, task_id=task_id
        )
        self.assertIsNotNone(pending_id)
        await self.conn.commit()
        body = {"value": "retry", "expected_version": 1}
        async with self.conn.transaction():
            await decide_task_retry(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "noura",
                body,
                idempotency_key="retry-once",
                packs_dir=self.packs_dir,
            )
        async with self.conn.transaction():
            replay = await decide_task_retry(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "noura",
                body,
                idempotency_key="retry-once",
                packs_dir=self.packs_dir,
            )
        self.assertIn("new_task_id", replay)
        cur = await self.conn.execute(
            "select count(*) from work.tasks where instance_id = %s and template = 'supplier_lookup'",
            (inst,),
        )
        self.assertEqual((await cur.fetchone())[0], 2)

    async def test_stale_retry_decision_voids_card(self) -> None:
        inst = "QQ-R08"
        task_id = await self._insert_created_task(self.conn, instance_id=inst, state="intake")
        await self.conn.execute(
            "update work.tasks set state = 'EXCEPTION' where id = %s",
            (task_id,),
        )
        pending_id = await open_task_retry_pending(
            self.conn, org=ORG, org_id=ORG_ID, instance_id=inst, task_id=task_id
        )
        await self.conn.execute("update work.instances set state = 'shortlisting', version = 2 where id = %s", (inst,))
        await self.conn.commit()
        try:
            await decide_task_retry(
                self.conn,
                ORG,
                ORG_ID,
                pending_id,
                "faisal",
                {"value": "retry", "expected_version": 2},
                idempotency_key=None,
                packs_dir=self.packs_dir,
            )
            self.fail("expected stale retry to be refused")
        except decisions.DecisionError as exc:
            self.assertEqual(exc.code, "conflict")
        await self.conn.commit()
        pcur = await self.conn.execute(
            "select status from work.pending_items where id = %s",
            (pending_id,),
        )
        self.assertEqual((await pcur.fetchone())[0], "voided")

    async def test_apply_event_voids_retry_when_leaving_state(self) -> None:
        inst = "QQ-R09"
        task_id = await self._insert_created_task(self.conn, instance_id=inst, state="intake")
        await self.conn.execute("update work.tasks set state = 'EXCEPTION' where id = %s", (task_id,))
        pending_id = await open_task_retry_pending(
            self.conn, org=ORG, org_id=ORG_ID, instance_id=inst, task_id=task_id
        )
        await self.conn.commit()
        async with self.conn.transaction():
            result = await workflow.apply_event(
                self.conn,
                inst,
                "decision.brief_confirmed",
                by_role="requester",
                packs_dir=self.packs_dir,
                org=ORG,
                actor={"kind": "person", "id": "faisal"},
            )
        self.assertTrue(result.applied)
        pcur = await self.conn.execute(
            "select status from work.pending_items where id = %s",
            (pending_id,),
        )
        self.assertEqual((await pcur.fetchone())[0], "voided")


if __name__ == "__main__":
    unittest.main()
