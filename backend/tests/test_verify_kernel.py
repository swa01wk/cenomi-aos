"""Kernel integration tests for verifier runner and submit pipeline (M2-AG-03)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg

from aos.kernel import context, ids, verify
from aos.kernel.contracts import _canonical_json, contract_hash
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO
from aos.kernel.worker_fence import ClaimedAttempt
from aos.kernel.worker_submit import submit_result

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
SEAT = "seat_sourcing_poc"


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


def _contract(
    *,
    role: str = "requester",
    person: str = "faisal",
    skill: str = "request_intake",
) -> dict:
    c = {
        "schema_version": "aos.task_contract/1",
        "contract_id": ids.new_contract_id(),
        "contract_version": 1,
        "permission_scope": {"classification_ceiling": "internal", "resources": []},
        "on_behalf_of": {"role": role, "person_id": person},
        "skill": {"name": skill, "version": 1, "instructions_sha256": "a" * 64},
        "pack": {"name": "procurement_demo", "version": 1, "digest": "b" * 64},
        "budget": {"cost_usd": 1, "retries": 3},
        "expected_outputs": [{"artifact_type": "brief", "cardinality": "one"}],
    }
    c["contract_hash"] = contract_hash(c)
    return c


async def _insert_job(conn, pack_version_id: str, instance_id: str) -> None:
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version, status,
          attributes, created_by, correlation_id
        ) values (%s, %s, 'quick_quote', %s, %s, 1, 'Test', 'intake', 1, 'running', '{}', 'faisal', %s)
        """,
        (instance_id, ORG_ID, pack_version_id, SEAT, f"corr_{instance_id}"),
    )
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, 'requester', 'faisal', 'creation')",
        (instance_id,),
    )


async def _brief_output(
    conn,
    *,
    instance_id: str,
    attempt_id: str,
    content: dict,
) -> dict:
    aid = ids.new_artifact_id()
    ch = hashlib.sha256(_canonical_json(content)).hexdigest()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'brief', '', 'Brief', 'draft', 1)",
        (aid, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'attempt', %s, '[]', '[]')",
        (aid, json.dumps(content), ch, attempt_id),
    )
    return {"artifact_id": aid, "version": 1, "content_hash": ch}


def _claimed(
    *,
    instance_id: str,
    task_id: str,
    attempt_id: str,
    contract: dict,
    attempt_n: int = 1,
    attempts_used: int = 1,
    max_attempts: int = 3,
) -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id=attempt_id,
        task_id=task_id,
        instance_id=instance_id,
        org_id=ORG_ID,
        seat=SEAT,
        seat_version=1,
        correlation_id=f"corr_{instance_id}",
        fencing_token=1,
        attempt_n=attempt_n,
        turn_id=None,
        kind="task",
        contract=contract,
        reserved_usd=1.0,
        usage={},
        worker_id="w-verify",
        task_state="RUNNING",
        attempts_used=attempts_used,
        max_attempts=max_attempts,
    )


@unittest.skipUnless(_pg.available(), "no local Postgres")
class VerifyKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs_dir = Path(tempfile.mkdtemp(prefix="aos-packs-verify-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs_dir / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))
        await self.conn.execute(seed_sql(ORG))
        self.pack_version_id = await _sync_published(self.conn, self.packs_dir)
        await self.conn.commit()

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs_dir, ignore_errors=True)

    async def test_implementation_outside_aos_verifiers_fails_closed(self) -> None:
        inst = "QQ-V01"
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()
        contract = _contract()
        gate = _claimed(instance_id=inst, task_id=task_id, attempt_id=attempt_id, contract=contract)
        defs = {
            "Verifier": {"evil": {"spec": {"implementation": "os.system"}}},
            "ArtifactType": {},
        }
        verdict, findings = await verify.run_task_verifier(
            self.conn,
            verifier_name="evil",
            defs=defs,
            gate=gate,
            result={"output_artifact_refs": []},
        )
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(findings)

    async def test_submit_stores_verification_and_emits_event(self) -> None:
        inst = "QQ-V02"
        await _insert_job(self.conn, self.pack_version_id, inst)
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()
        contract = _contract()
        brief = {
            "title": "T",
            "category": "CAT-JAN-EQ",
            "quantity": 2,
            "specification": "s",
            "delivery_date": "2030-01-01",
            "delivery_site": "Riyadh",
        }
        out_ref = await _brief_output(self.conn, instance_id=inst, attempt_id=attempt_id, content=brief)
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema',
                      'RUNNING', %s, %s, 3, 1, 1)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        await self.conn.execute(
            "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id)"
            " values (%s, %s, 1, 1, 'CLAIMED', 1.0, 'w-verify')",
            (attempt_id, task_id),
        )
        await self.conn.execute(
            """
            update work.attempts set tool_observations = %s where id = %s
            """,
            (
                json.dumps(
                    [
                        {
                            "tool": "browse_categories",
                            "args": {"query": "t"},
                            "receipt_ref": "tp_cat",
                            "content": {"items": [{"id": "CAT-JAN-EQ", "name": "Janitorial"}]},
                        }
                    ]
                ),
                attempt_id,
            ),
        )
        await submit_result(
            self.conn,
            org=ORG,
            org_id=ORG_ID,
            attempt_id=attempt_id,
            worker_id="w-verify",
            fencing_token=1,
            result={
                "attempt_id": attempt_id,
                "contract_id": contract["contract_id"],
                "status": "completed",
                "summary": "Brief ready.",
                "output_artifact_refs": [out_ref],
                "input_versions": {},
            },
            packs_dir=self.packs_dir,
        )
        vcur = await self.conn.execute(
            "select verification from work.artifact_versions where artifact_id = %s and version = 1",
            (out_ref["artifact_id"],),
        )
        ver = (await vcur.fetchone())[0]
        self.assertEqual(ver["verifier"], "brief_schema")
        self.assertEqual(ver["verdict"], "PASS")
        self.assertEqual(set(ver.keys()), {"verifier", "verdict", "findings"})
        ocur = await self.conn.execute(
            "select audience, data from evidence.outbox where event_type = 'verification.completed'"
            " and instance_id = %s",
            (inst,),
        )
        row = await ocur.fetchone()
        self.assertIsNotNone(row)
        audience = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        self.assertEqual(audience, {"roles": ["requester"]})

    async def test_previous_verification_on_next_attempt(self) -> None:
        verify.register_implementation(
            "aos.verifiers.brief_schema",
            lambda _inp: ("REWORK", ["title: fix it"]),
        )
        self.addCleanup(verify.unregister_implementation, "aos.verifiers.brief_schema")
        inst = "QQ-V03"
        await _insert_job(self.conn, self.pack_version_id, inst)
        task_id = ids.new_task_id()
        attempt1 = ids.new_attempt_id()
        attempt2 = ids.new_attempt_id()
        contract = _contract()
        out_ref = await _brief_output(
            self.conn, instance_id=inst, attempt_id=attempt1, content={"title": "x"}
        )
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema',
                      'RUNNING', %s, %s, 3, 1, 1)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        for aid, n in ((attempt1, 1),):
            await self.conn.execute(
                "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id,"
                " outcome, submit_response)"
                " values (%s, %s, %s, 1, 'ENDED', 1.0, 'w-verify', 'submitted', %s)",
                (
                    aid,
                    task_id,
                    n,
                    json.dumps(
                        {
                            "verdict": "REWORK",
                            "verifier": {"name": "brief_schema", "verdict": "REWORK", "findings": ["title: fix it"]},
                        }
                    ),
                ),
            )
        await self.conn.execute(
            "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id)"
            " values (%s, %s, 2, 2, 'CLAIMED', 1.0, 'w-verify')",
            (attempt2, task_id),
        )
        gate = _claimed(
            instance_id=inst,
            task_id=task_id,
            attempt_id=attempt2,
            contract=contract,
            attempt_n=2,
            attempts_used=2,
        )
        env = await context.assemble_context(
            self.conn,
            org=ORG,
            gate=gate,
            refresh_reason="start",
            packs_dir=self.packs_dir,
        )
        self.assertIsInstance(env, dict)
        pv = env.get("previous_verification")
        self.assertIsNotNone(pv)
        self.assertEqual(pv["attempt_n"], 1)
        self.assertEqual(pv["verifier"], "brief_schema")
        self.assertIn("title", pv["findings"][0])

    async def test_rework_on_last_attempt_exception_and_retry_card(self) -> None:
        verify.register_implementation(
            "aos.verifiers.brief_schema",
            lambda _inp: ("REWORK", ["title: fix it"]),
        )
        self.addCleanup(verify.unregister_implementation, "aos.verifiers.brief_schema")
        inst = "QQ-V04"
        await _insert_job(self.conn, self.pack_version_id, inst)
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()
        contract = _contract()
        brief = {
            "title": "T",
            "category": "CAT-JAN-EQ",
            "quantity": 1,
            "specification": "s",
            "delivery_date": "2030-01-01",
            "delivery_site": "Riyadh",
        }
        out_ref = await _brief_output(self.conn, instance_id=inst, attempt_id=attempt_id, content=brief)
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema',
                      'RUNNING', %s, %s, 1, 1, 1)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        await self.conn.execute(
            "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id)"
            " values (%s, %s, 1, 1, 'CLAIMED', 1.0, 'w-verify')",
            (attempt_id, task_id),
        )
        resp = await submit_result(
            self.conn,
            org=ORG,
            org_id=ORG_ID,
            attempt_id=attempt_id,
            worker_id="w-verify",
            fencing_token=1,
            result={
                "attempt_id": attempt_id,
                "contract_id": contract["contract_id"],
                "status": "completed",
                "summary": "Needs fix.",
                "output_artifact_refs": [out_ref],
                "input_versions": {},
            },
            packs_dir=self.packs_dir,
        )
        self.assertEqual(resp["task_state"], "EXCEPTION")
        tcur = await self.conn.execute("select state from work.tasks where id = %s", (task_id,))
        self.assertEqual((await tcur.fetchone())[0], "EXCEPTION")
        pcur = await self.conn.execute(
            "select count(*) from work.pending_items where instance_id = %s and event = 'task.retry'",
            (inst,),
        )
        self.assertEqual(int((await pcur.fetchone())[0]), 1)

    async def test_leak_rework_then_pass(self) -> None:
        inst = "QQ-V05"
        await _insert_job(self.conn, self.pack_version_id, inst)
        task_id = ids.new_task_id()
        contract = _contract(role="buyer", person="noura", skill="rfq_authoring")
        contract["permission_scope"] = {"classification_ceiling": "shareable", "resources": []}
        contract["expected_outputs"] = [{"artifact_type": "rfq_email", "cardinality": "many"}]
        contract["contract_hash"] = contract_hash(contract)
        await self.conn.execute(
            """
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (%s, %s, 'task', 'rfq_draft', 'rfq_authoring', 'document_draft', 'leak_check',
                      'RUNNING', %s, %s, 2, 1, 1)
            """,
            (task_id, inst, json.dumps(contract), contract["contract_hash"]),
        )
        brief_id = ids.new_artifact_id()
        brief_content = {"title": "T", "budget_guidance": 40000}
        bch = hashlib.sha256(_canonical_json(brief_content)).hexdigest()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'brief', '', 'Brief', 'draft', 1)",
            (brief_id, inst),
        )
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 1, %s, %s, 'person', 'faisal', '[]', '[]')",
            (brief_id, json.dumps(brief_content), bch),
        )

        rfq_artifact_id: str | None = None

        async def _rfq_attempt(n: int, body: str) -> dict:
            nonlocal rfq_artifact_id
            attempt_id = ids.new_attempt_id()
            tcur = await self.conn.execute(
                "select fencing_token from work.tasks where id = %s",
                (task_id,),
            )
            fencing_token = int((await tcur.fetchone())[0])
            content = {
                "supplier_id": "SUP-1",
                "to": "a@b.c",
                "subject": "RFQ",
                "body": body,
            }
            ch = hashlib.sha256(_canonical_json(content)).hexdigest()
            if rfq_artifact_id is None:
                aid = ids.new_artifact_id()
                rfq_artifact_id = aid
                version = 1
                await self.conn.execute(
                    "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
                    " values (%s, %s, 'rfq_email', 'SUP-1', 'Email', 'draft', 1)",
                    (aid, inst),
                )
            else:
                aid = rfq_artifact_id
                vcur = await self.conn.execute(
                    "select latest_version from work.artifacts where id = %s",
                    (aid,),
                )
                version = int((await vcur.fetchone())[0]) + 1
                await self.conn.execute(
                    "update work.artifacts set latest_version = %s where id = %s",
                    (version, aid),
                )
            await self.conn.execute(
                "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
                " produced_by_kind, produced_by, inputs, sources)"
                " values (%s, %s, %s, %s, 'attempt', %s, '[]', '[]')",
                (aid, version, json.dumps(content), ch, attempt_id),
            )
            await self.conn.execute(
                "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id)"
                " values (%s, %s, %s, %s, 'CLAIMED', 1.0, 'w-verify')",
                (attempt_id, task_id, n, fencing_token),
            )
            return await submit_result(
                self.conn,
                org=ORG,
                org_id=ORG_ID,
                attempt_id=attempt_id,
                worker_id="w-verify",
                fencing_token=fencing_token,
                result={
                    "attempt_id": attempt_id,
                    "contract_id": contract["contract_id"],
                    "status": "completed",
                    "summary": "Draft.",
                    "output_artifact_refs": [{"artifact_id": aid, "version": version, "content_hash": ch}],
                    "input_versions": {},
                },
                packs_dir=self.packs_dir,
            )

        resp1 = await _rfq_attempt(1, "Please quote; budget 40,000 SAR.")
        self.assertEqual(resp1["verdict"], "REWORK")
        await self.conn.execute(
            "update work.tasks set state = 'RUNNING', attempts_used = 2, fencing_token = 2 where id = %s",
            (task_id,),
        )
        resp2 = await _rfq_attempt(2, "Please quote for the trolleys.")
        self.assertEqual(resp2["verdict"], "ACCEPTED")
        self.assertEqual(resp2["task_state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
