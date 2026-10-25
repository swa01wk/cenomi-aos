"""M2-BE-07: conversation follows the job (ADR 015)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel import ids, progress, tasks as task_ops
from aos.kernel.auth import issue_worker_token
from aos.kernel.contracts import contract_hash, finalize_assist_contract
from aos.kernel.worker_attempts import expire_one_attempt
from aos.kernel.org import load_org
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ConversationFollowsJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-conv-job-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        cls.settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
        )
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()
        cls.version_id = cls.client.post(
            "/api/console/packs/procurement_demo/sync",
            headers=cls._auth("platform_admin"),
            json={"source": "test"},
        ).json()["pack_version_id"]
        cls._publish_and_activate()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    @classmethod
    def _auth(cls, person: str) -> dict:
        token = cls.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def login(self, person: str) -> dict:
        return self._auth(person)

    def worker_auth(self, worker_id: str = "w-conv") -> dict:
        token = issue_worker_token(ORG_ID, worker_id, self.settings.session_secret)
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def _publish_and_activate(cls) -> None:
        cls.client.post(
            f"/api/console/pack-versions/{cls.version_id}/publish-requests",
            headers=cls._auth("platform_admin"),
        )
        req = cls.client.get("/api/console/publish-requests", headers=cls._auth("risk")).json()["items"][0]
        cls.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("risk"),
            json={"part": "policies"},
        )
        cls.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("head_of_procurement"),
            json={"part": "seats_and_workflows"},
        )
        from aos.kernel.seats import insert_seats_for_published_pack

        async def _seats() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(cls.db)) as conn:
                async with conn.transaction():
                    await insert_seats_for_published_pack(
                        conn, org=ORG, org_id=ORG_ID, pack_version_id=cls.version_id
                    )

        asyncio.run(_seats())
        seat = cls.client.get(f"/api/console/seats/{SEAT}", headers=cls._auth("platform_admin")).json()
        configured = cls.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=cls._auth("platform_admin"),
            json={"version": 1, "expected_version": seat["record_version"]},
        ).json()
        rv = configured["record_version"]
        _pg.admin_sql(
            cls.db,
            f"""
            update registry.seats set state = 'APPROVED', record_version = {rv}
            where org_id = '{ORG_ID}' and name = '{SEAT}' and version = 1;
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_cf_refusals', '{ORG_ID}', '{SEAT}', 1, 'refusals', 'fake', 'passed', 4, 4),
              ('ev_cf_dry', '{ORG_ID}', '{SEAT}', 1, 'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )
        cls.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=cls._auth("head_of_procurement"),
            json={"version": 1, "expected_version": rv},
        )

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            """
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.turns;
            delete from work.attempts;
            delete from work.pending_items;
            delete from work.instance_transitions;
            delete from work.timers;
            delete from work.regions;
            delete from work.artifact_versions;
            delete from work.artifacts;
            delete from work.tasks;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            delete from gov.decision_records;
            update registry.seats set state = 'ACTIVE'
            where org_id = '%s' and name = '%s' and version = 1;
            """
            % (ORG_ID, SEAT),
        )

    def _start(self, person: str = "faisal", message: str = "Need trolleys") -> str:
        r = self.client.post(
            "/api/instances",
            headers=self.login(person),
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": message},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["instance_id"]

    def _complete_assist(
        self,
        inst_id: str,
        person: str,
        client_turn_id: str,
        text: str = "ok",
        *,
        post: bool = True,
    ) -> None:
        if post:
            tr = self.client.post(
                f"/api/instances/{inst_id}/turns",
                headers=self.login(person),
                json={"text": text, "client_turn_id": client_turn_id},
            )
            self.assertEqual(tr.status_code, 202, tr.text)
            attempt_id = tr.json()["attempt_id"]
        else:
            attempt_id = _pg.admin_sql(
                self.db,
                f"""
                select a.id from work.attempts a
                join work.tasks t on t.id = a.task_id
                where t.instance_id = '{inst_id}' and t.kind = 'assist'
                order by a.admitted_at desc limit 1;
                """,
            ).stdout.strip()
        self.assertIsNotNone(attempt_id)
        self.assertTrue(attempt_id)
        claim = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth(),
            json={"worker_id": "w-conv", "lanes": ["assist"]},
        )
        self.assertEqual(claim.status_code, 200, claim.text)
        body = claim.json()
        self.assertEqual(body["attempt_id"], attempt_id)
        sub = self.client.post(
            f"/api/worker/attempts/{attempt_id}/submit",
            headers={
                **self.worker_auth(),
                "X-AOS-Fencing-Token": str(body["fencing_token"]),
            },
            json={
                "attempt_id": attempt_id,
                "contract_id": body["contract"]["contract_id"],
                "status": "completed",
                "summary": "Done.",
                "reply_blocks": [{"kind": "text", "text": "Reply."}],
                "output_artifact_refs": [],
                "input_versions": {},
            },
        )
        self.assertEqual(sub.status_code, 200, sub.text)

    def test_refused_post_turn_leaves_no_turn_row(self) -> None:
        inst = self._start()
        _pg.admin_sql(
            self.db,
            f"update registry.seats set state = 'PAUSED' where org_id = '{ORG_ID}' and name = '{SEAT}'",
        )
        before = int(_pg.admin_sql(self.db, "select count(*) from work.turns").stdout.strip())
        r = self.client.post(
            f"/api/instances/{inst}/turns",
            headers=self.login("faisal"),
            json={"text": "Another", "client_turn_id": "refused-turn"},
        )
        self.assertEqual(r.status_code, 403, r.text)
        after = int(_pg.admin_sql(self.db, "select count(*) from work.turns").stdout.strip())
        self.assertEqual(before, after)

    def test_seventh_message_admitted(self) -> None:
        inst = self._start()
        self._complete_assist(inst, "faisal", "turn-1", post=False)
        for i in range(2, 8):
            self._complete_assist(inst, "faisal", f"turn-{i}", f"Message {i}")

    def test_shortlisting_uses_sourcing_assist_contract(self) -> None:
        inst = self._start()
        self._complete_assist(inst, "faisal", "intake-1", post=False)
        _pg.admin_sql(
            self.db,
            f"update work.instances set state = 'shortlisting' where id = '{inst}';"
            f"insert into work.participants (instance_id, role, person_id, bound_by)"
            f" values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;",
        )
        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers=self.login("noura"),
            json={"text": "Where are we?", "client_turn_id": "buyer-shortlist"},
        )
        self.assertEqual(tr.status_code, 202, tr.text)
        async def _contract() -> dict:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                cur = await conn.execute(
                    "select contract from work.tasks where instance_id = %s and kind = 'assist'",
                    (inst,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {}
                c = row[0]
                return c if isinstance(c, dict) else json.loads(c)

        contract = asyncio.run(_contract())
        self.assertEqual((contract.get("skill") or {}).get("name"), "sourcing_assist")
        ev = _pg.admin_sql(
            self.db,
            "select contract_version, attributes->>'contract_hash' from evidence.execution_events"
            " where event_type = 'TaskDispatched' order by aggregate_seq desc limit 1",
        ).stdout.strip().split("|")
        self.assertTrue(int(ev[0].strip()) >= 1)
        self.assertTrue(len(ev[1].strip()) == 64)

    def test_intake_and_shortlisting_dispatch_different_contract_versions(self) -> None:
        inst = self._start()
        self._complete_assist(inst, "faisal", "intake-ev", post=False)
        v1 = _pg.admin_sql(
            self.db,
            "select contract_version from evidence.execution_events where event_type = 'TaskDispatched'"
            " order by aggregate_seq asc limit 1",
        ).stdout.strip()
        _pg.admin_sql(
            self.db,
            f"""
            update work.instances set state = 'shortlisting' where id = '{inst}';
            insert into work.participants (instance_id, role, person_id, bound_by)
            values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;
            """,
        )
        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers=self.login("noura"),
            json={"text": "Hi", "client_turn_id": "short-ev"},
        )
        self.assertEqual(tr.status_code, 202, tr.text)
        claim = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth("w-conv2"),
            json={"worker_id": "w-conv2", "lanes": ["assist"]},
        ).json()
        v2 = claim["contract"]["contract_version"]
        self.assertGreater(int(v2), int(v1))
        self.assertNotEqual(
            (claim["contract"].get("skill") or {}).get("name"),
            "request_intake",
        )

    def test_decision_open_progress_pending_ref_buyer_only(self) -> None:
        inst = self._start()
        pending_id = ids.new_pending_id()

        async def _open() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        insert into work.pending_items (
                          id, instance_id, kind, event, title, for_role, for_person_id, options, status
                        ) values (%s, %s, 'decision', 'decision.shortlist_confirmed', 'Confirm the shortlist',
                                  'buyer', 'noura', '[]', 'open')
                        """,
                        (pending_id, inst),
                    )
                    await progress.post_decision_opened_progress(
                        conn,
                        org=ORG,
                        org_id=ORG_ID,
                        instance_id=inst,
                        pending_id=pending_id,
                        label="Confirm the shortlist",
                        for_person_id="noura",
                        for_role="buyer",
                    )

        asyncio.run(_open())
        buyer_turns = _pg.admin_sql(
            self.db,
            f"select blocks from work.turns where instance_id = '{inst}' and author_kind = 'seat'",
        ).stdout
        self.assertIn("pending_ref", buyer_turns)
        self.assertIn(pending_id, buyer_turns)
        faisal_snap = self.client.get(f"/api/instances/{inst}", headers=self.login("faisal")).json()
        for t in faisal_snap.get("turns") or []:
            blob = json.dumps(t.get("blocks") or [])
            self.assertNotIn(pending_id, blob)

    def test_task_progress_summary_redacted_for_clearance(self) -> None:
        inst = self._start()
        task_id = ids.new_task_id()
        contract = {
            "schema_version": "aos.task_contract/1",
            "contract_id": ids.new_contract_id(),
            "contract_version": 1,
            "permission_scope": {"classification_ceiling": "restricted", "resources": []},
            "on_behalf_of": {"role": "requester", "person_id": "faisal"},
            "budget": {"cost_usd": 1},
        }
        contract["contract_hash"] = contract_hash(contract)

        async def _seed() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        insert into work.tasks (
                          id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
                        ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'COMPLETED',
                                  %s, %s, 3)
                        """,
                        (task_id, inst, json.dumps(contract), contract["contract_hash"]),
                    )
                    await progress.post_task_outcome_progress(
                        conn,
                        org=ORG,
                        org_id=ORG_ID,
                        instance_id=inst,
                        task_id=task_id,
                        summary="Restricted supplier totals inside.",
                        attempt_id=None,
                    )

        asyncio.run(_seed())
        row = _pg.admin_sql(
            self.db,
            f"select blocks from work.turns where instance_id = '{inst}' and author_kind = 'seat' order by seq desc limit 1",
        ).stdout
        self.assertNotIn("Restricted supplier", row)
        self.assertIn("Intake", row)

    def test_job_snapshot_open_decision(self) -> None:
        inst = self._start()
        pending_id = ids.new_pending_id()
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.participants (instance_id, role, person_id, bound_by)
            values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;
            insert into work.pending_items (
              id, instance_id, kind, event, title, for_role, for_person_id, options, status
            ) values ('{pending_id}', '{inst}', 'decision', 'decision.shortlist_confirmed',
                      'Confirm the shortlist', 'buyer', 'noura', '[]', 'open');
            update work.instances set state = 'shortlisting' where id = '{inst}';
            """,
        )

        async def _snap() -> dict:
            from aos.kernel.context import assemble_context
            from aos.kernel.worker_fence import ClaimedAttempt

            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                tcur = await conn.execute(
                    "select id, contract from work.tasks where instance_id = %s and kind = 'assist' limit 1",
                    (inst,),
                )
                task_id, cj = (await tcur.fetchone()) or (None, {})
                contract = cj if isinstance(cj, dict) else json.loads(cj or "{}")
                contract["skill"] = {"name": "sourcing_assist", "version": 1, "instructions_sha256": "a" * 64}
                contract["on_behalf_of"] = {"role": "buyer", "person_id": "noura"}
                gate = ClaimedAttempt(
                    attempt_id=ids.new_attempt_id(),
                    task_id=task_id or ids.new_task_id(),
                    instance_id=inst,
                    org_id=ORG_ID,
                    seat=SEAT,
                    seat_version=1,
                    correlation_id="c",
                    fencing_token=1,
                    attempt_n=1,
                    turn_id=None,
                    kind="assist",
                    contract=contract,
                    reserved_usd=1.0,
                    usage={},
                    worker_id="test",
                    task_state="RUNNING",
                    attempts_used=1,
                    max_attempts=3,
                )
                env = await assemble_context(
                    conn, org=ORG, gate=gate, refresh_reason="start", packs_dir=self.packs
                )
                assert isinstance(env, dict)
                return env["resolvers"]["job_snapshot"]

        snap = asyncio.run(_snap())
        self.assertEqual(len(snap["open_decisions"]), 1)
        self.assertEqual(snap["open_decisions"][0]["waiting_on"]["name"], "Noura")
        self.assertEqual(snap["open_decisions"][0]["waiting_on"]["role"], "buyer")

    def test_turn_retry_shares_budget(self) -> None:
        inst = self._start()
        self._complete_assist(inst, "faisal", "first-msg", post=False)
        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers=self.login("faisal"),
            json={"text": "Once", "client_turn_id": "retry-budget"},
        )
        self.assertEqual(tr.status_code, 202, tr.text)
        self.assertIsNotNone(tr.json()["attempt_id"])
        turn_id = _pg.admin_sql(
            self.db,
            "select id from work.turns where client_turn_id = 'retry-budget'",
        ).stdout.strip()
        task_id = _pg.admin_sql(
            self.db,
            f"select id from work.tasks where instance_id = '{inst}' and kind = 'assist'",
        ).stdout.strip()

        async def _counts() -> tuple[int, int]:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                n1 = await task_ops.count_attempts_for_turn(conn, task_id, turn_id)
                await conn.execute(
                    "update work.attempts set state = 'ENDED', outcome = 'expired' where turn_id = %s",
                    (turn_id,),
                )
                n2 = await task_ops.count_attempts_for_turn(conn, task_id, turn_id)
                return n1, n2

        before, after_expire = asyncio.run(_counts())
        self.assertEqual(before, 1)
        self.assertEqual(after_expire, 1)

    def test_stored_assist_contract_hash_matches_canonical(self) -> None:
        inst = self._start()

        async def _check() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                cur = await conn.execute(
                    "select contract from work.tasks where instance_id = %s and kind = 'assist'",
                    (inst,),
                )
                row = await cur.fetchone()
                assert row is not None
                stored = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                body_hash = contract_hash({k: v for k, v in stored.items() if k != "contract_hash"})
                self.assertEqual(stored["contract_hash"], body_hash)

        asyncio.run(_check())

    def test_assist_contract_version_stable_in_same_state(self) -> None:
        inst = self._start()
        self._complete_assist(inst, "faisal", "v-stable-1", post=False)
        self._complete_assist(inst, "faisal", "v-stable-2")

        async def _versions() -> list[int]:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                cur = await conn.execute(
                    "select contract_version from evidence.execution_events"
                    " where event_type = 'TaskDispatched' order by aggregate_seq",
                )
                return [int(r[0]) for r in await cur.fetchall() if r[0] is not None]

        versions = asyncio.run(_versions())
        self.assertEqual(len(set(versions)), 1)

    def test_assist_contract_version_bumps_when_assist_skill_changes(self) -> None:
        prev = {
            "schema_version": "aos.task_contract/1",
            "contract_id": "c1",
            "contract_version": 1,
            "skill": {"name": "request_intake", "version": 1},
            "objective": "x",
            "contract_hash": "abc",
        }
        nxt = dict(prev)
        nxt["skill"] = {"name": "sourcing_assist", "version": 1}
        nxt.pop("contract_hash", None)
        nxt.pop("contract_version", None)
        out = finalize_assist_contract(nxt, previous=prev)
        self.assertEqual(out["contract_version"], 2)
        self.assertEqual(out["contract_id"], "c1")
        self.assertEqual(out["contract_hash"], contract_hash(out))

    def test_finalize_keeps_previous_when_materially_unchanged(self) -> None:
        prev = finalize_assist_contract(
            {"schema_version": "aos.task_contract/1", "contract_id": "c1", "skill": {"name": "a"}},
            previous=None,
        )
        draft = dict(prev)
        draft["idempotency_key"] = "different"
        out = finalize_assist_contract(draft, previous=prev)
        self.assertIs(out, prev)

    def test_task_progress_reaches_buyer_bound_after_task_created(self) -> None:
        inst = self._start()
        task_id = ids.new_task_id()
        contract = {
            "schema_version": "aos.task_contract/1",
            "contract_id": ids.new_contract_id(),
            "contract_version": 1,
            "permission_scope": {"classification_ceiling": "internal", "resources": []},
            "on_behalf_of": {"role": "buyer", "person_id": None},
            "budget": {"cost_usd": 1},
        }
        contract["contract_hash"] = contract_hash(contract)

        async def _run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        insert into work.tasks (
                          id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
                        ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'COMPLETED',
                                  %s, %s, 3)
                        """,
                        (task_id, inst, json.dumps(contract), contract["contract_hash"]),
                    )
                    await conn.execute(
                        "insert into work.participants (instance_id, role, person_id, bound_by)"
                        " values (%s, 'buyer', 'noura', 'claim') on conflict do nothing",
                        (inst,),
                    )
                    await progress.post_task_outcome_progress(
                        conn,
                        org=ORG,
                        org_id=ORG_ID,
                        instance_id=inst,
                        task_id=task_id,
                        summary="Lookup finished.",
                        attempt_id=None,
                    )

        asyncio.run(_run())
        row = _pg.admin_sql(
            self.db,
            f"select blocks from work.turns where instance_id = '{inst}' and author_kind = 'seat' order by seq desc limit 1",
        ).stdout
        self.assertIn("Lookup finished", row)

    def test_decision_resolved_progress_when_job_moves(self) -> None:
        from aos.kernel import decisions as dec_ops
        from tests.test_decisions import _brief_v, _insert_brief, _insert_task_completed

        inst = self._start()

        async def _brief_and_decide() -> str:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await _insert_task_completed(conn, inst, "request_intake")
                    aid = await _insert_brief(conn, inst, [_brief_v(1), _brief_v(2)])
                    await conn.execute(
                        "update work.artifacts set status = 'final' where id = %s",
                        (aid,),
                    )
                    opened = await dec_ops.open_ready_decisions(
                        conn, inst, org=ORG, packs_dir=self.packs
                    )
                    self.assertEqual(len(opened), 1)
                    pend = opened[0]
                    cur = await conn.execute("select version from work.instances where id = %s", (inst,))
                    inst_v = int((await cur.fetchone())[0])
                    await dec_ops.decide_pending(
                        conn,
                        ORG,
                        ORG_ID,
                        pend,
                        "faisal",
                        {
                            "value": "confirm",
                            "expected_version": inst_v,
                            "artifact_version": 2,
                        },
                        idempotency_key=str(uuid.uuid4()),
                        packs_dir=self.packs,
                    )
                    cur = await conn.execute(
                        "select blocks from work.turns where instance_id = %s and author_kind = 'seat'"
                        " and blocks::text like '%%decided:%%' order by seq desc limit 1",
                        (inst,),
                    )
                    row = await cur.fetchone()
                    return json.dumps(row[0]) if row else ""

        text = asyncio.run(_brief_and_decide())
        self.assertIn("Faisal decided:", text)
        self.assertIn("Confirm the brief", text)

    def test_decision_resolved_progress_when_job_unchanged(self) -> None:
        from aos.kernel import decisions as dec_ops
        from tests.test_decisions import _insert_supplier_list, _region_done

        inst = self._start()

        async def _run() -> str:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        "insert into work.participants (instance_id, role, person_id, bound_by)"
                        " values (%s, 'buyer', 'noura', 'claim') on conflict do nothing",
                        (inst,),
                    )
                    await conn.execute(
                        "update work.instances set state = 'shortlisting', version = 2 where id = %s",
                        (inst,),
                    )
                    await _insert_supplier_list(conn, inst, sids=("s1", "s2", "s3"))
                    await _region_done(conn, inst)
                    opened = await dec_ops.open_ready_decisions(
                        conn, inst, org=ORG, packs_dir=self.packs
                    )
                    pend = opened[0]
                    await dec_ops.decide_pending(
                        conn,
                        ORG,
                        ORG_ID,
                        pend,
                        "noura",
                        {
                            "value": "confirm",
                            "expected_version": 2,
                            "artifact_version": 1,
                            "selection": ["s1", "s2"],
                        },
                        idempotency_key=str(uuid.uuid4()),
                        packs_dir=self.packs,
                    )
                    cur = await conn.execute(
                        "select blocks from work.turns where instance_id = %s and author_kind = 'seat'"
                        " and blocks::text like '%%still in%%' order by seq desc limit 1",
                        (inst,),
                    )
                    row = await cur.fetchone()
                    return json.dumps(row[0]) if row else ""

        text = asyncio.run(_run())
        self.assertIn("still in Shortlisting", text)

    def test_verifier_rework_posts_task_progress(self) -> None:
        from aos.kernel import verify

        def _rework(_inp):
            return "REWORK", ["fix the draft"]

        verify.register_implementation("aos.verifiers.brief_schema", _rework)
        self.addCleanup(verify.unregister_implementation, "aos.verifiers.brief_schema")
        inst = self._start()
        task_id = ids.new_task_id()
        contract = {
            "schema_version": "aos.task_contract/1",
            "contract_id": ids.new_contract_id(),
            "contract_version": 1,
            "permission_scope": {"classification_ceiling": "shareable", "resources": []},
            "on_behalf_of": {"role": "buyer", "person_id": None},
            "budget": {"cost_usd": 1},
        }
        contract["contract_hash"] = contract_hash(contract)
        attempt_id = ids.new_attempt_id()

        async def _submit() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        insert into work.tasks (
                          id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
                          max_attempts, fencing_token, attempts_used
                        ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema',
                                  'RUNNING', %s, %s, 3, 1, 1)
                        """,
                        (task_id, inst, json.dumps(contract), contract["contract_hash"]),
                    )
                    await conn.execute(
                        """
                        insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id)
                        values (%s, %s, 1, 1, 'CLAIMED', 1.0, 'w-rework')
                        """,
                        (attempt_id, task_id),
                    )
                    await conn.execute(
                        "update work.instances set seat = %s, seat_version = 1 where id = %s",
                        (SEAT, inst),
                    )
                    await conn.execute(
                        "insert into work.participants (instance_id, role, person_id, bound_by)"
                        " values (%s, 'buyer', 'noura', 'claim') on conflict do nothing",
                        (inst,),
                    )
                    from aos.kernel.worker_submit import submit_result

                    await submit_result(
                        conn,
                        org=ORG,
                        org_id=ORG_ID,
                        attempt_id=attempt_id,
                        worker_id="w-rework",
                        fencing_token=1,
                        result={
                            "attempt_id": attempt_id,
                            "contract_id": contract["contract_id"],
                            "status": "completed",
                            "summary": "Needs another pass.",
                            "output_artifact_refs": [],
                            "input_versions": {},
                        },
                        packs_dir=REPO / "packs",
                    )

        asyncio.run(_submit())
        resp = _pg.admin_sql(
            self.db,
            f"select state from work.tasks where id = '{task_id}'",
        ).stdout.strip()
        self.assertEqual(resp, "READY")
        row = _pg.admin_sql(
            self.db,
            f"select blocks from work.turns where instance_id = '{inst}' and author_kind = 'seat' order by seq",
        ).stdout
        self.assertIn("Needs another pass", row)

    def test_workflow_task_expires_to_exception_at_max_attempts(self) -> None:
        inst = self._start()
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()

        async def _run() -> str:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        insert into work.tasks (
                          id, instance_id, kind, template, skill, work_type, state, contract, contract_hash,
                          max_attempts, fencing_token, attempts_used
                        ) values (%s, %s, 'task', 'supplier_lookup', 'supplier_lookup', 'analysis', 'RUNNING',
                                  '{}', 'deadbeef', 2, 0, 2)
                        """,
                        (task_id, inst),
                    )
                    await conn.execute(
                        """
                        insert into work.attempts (
                          id, task_id, n, fencing_token, state, reserved_usd, lease_expires_at, worker_id
                        ) values (%s, %s, 2, 1, 'CLAIMED', 1.0, now() - interval '1 minute', 'w-exp')
                        """,
                        (attempt_id, task_id),
                    )
                    out = await expire_one_attempt(conn, attempt_id=attempt_id)
                    self.assertTrue(out.expired)
                    self.assertIsNone(out.readmit)
                    cur2 = await conn.execute("select state from work.tasks where id = %s", (task_id,))
                    return (await cur2.fetchone())[0]

        state = asyncio.run(_run())
        self.assertEqual(state, "EXCEPTION")


if __name__ == "__main__":
    unittest.main()
