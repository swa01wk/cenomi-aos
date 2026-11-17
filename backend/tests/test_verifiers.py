"""Rule verifiers and the REWORK loop (M2-AG-03): brief_schema, sources_cited, leak_check."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from aos.kernel import clock, contracts, ids
from aos.kernel.context import assemble_context
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import seed_sql
from aos.kernel.settings import REPO
from aos.kernel.worker_fence import evaluate_claimed_fence
from aos.kernel.worker_submit import submit_result
from aos.verifiers import supplier_scoring

from . import _pg
from .test_context_envelope import _schema_validator
from .test_decisions import ORG, ORG_ID, SEAT, _insert_instance, _sync_published
from .test_task_contracts import _defs_and_digest as _defs, _templates

TODAY = date(2026, 10, 21)


def _brief(**overrides) -> dict:
    content = {
        "title": "40 cleaning trolleys for Mall A",
        "category": "CAT-JAN-EQ",
        "quantity": 40,
        "specification": "Three-bucket trolley, 120 L, lockable caddy",
        "delivery_date": "2026-11-20",
        "delivery_site": "Mall A loading bay",
        "vendor_reply_deadline": "1.5 minutes",
        "budget_guidance": 15000,
    }
    content.update(overrides)
    return {k: v for k, v in content.items() if v is not None}


def _row(
    rank: int,
    sid: str,
    score: float | None = None,
    sources: list | None = None,
    *,
    past_pos: int = 3,
    on_time_pct: float | None = 100,
) -> dict:
    breakdown = supplier_scoring.score_breakdown(past_pos, on_time_pct)
    resolved = score if score is not None else breakdown["score"]
    return {
        "rank": rank,
        "supplier": f"Supplier {sid}",
        "supplier_id": sid,
        "past_pos": past_pos,
        "on_time_pct": on_time_pct,
        "points_asl": breakdown["points_asl"],
        "points_history": breakdown["points_history"],
        "points_delivery": breakdown["points_delivery"],
        "score": resolved,
        "sources": ["tp_search"] if sources is None else sources,
    }


class SupplierScoringRules(unittest.TestCase):
    def test_breakdown_sums_to_score(self) -> None:
        bd = supplier_scoring.score_breakdown(7, 71.4)
        self.assertEqual(bd, {"points_asl": 20, "points_history": 35, "points_delivery": 21, "score": 76})

    def test_no_history_skips_delivery_points(self) -> None:
        bd = supplier_scoring.score_breakdown(0, None)
        self.assertEqual(bd["points_delivery"], 0)
        self.assertEqual(bd["score"], 20)


class ReworkLoopTests(unittest.IsolatedAsyncioTestCase):
    """A brief that breaks a rule goes back with findings; the next attempt reads them and passes."""

    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.packs = Path(tempfile.mkdtemp(prefix="aos-packs-verify-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", self.packs / "procurement_demo")
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db), autocommit=True)
        await self.conn.execute(seed_sql(ORG))
        self.pvid = await _sync_published(self.conn, self.packs)
        self.inst = "QQ-V01"
        await _insert_instance(self.conn, instance_id=self.inst, pack_version_id=self.pvid, with_buyer=False)
        clock.set_frozen_wall(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
        self.addCleanup(clock.set_frozen_wall, None)

        defs, digest = _defs()
        tpl = _templates(defs)["request_intake"]
        self.task_id = ids.new_task_id()
        self.contract = contracts.build_task_contract(
            packs_dir=self.packs, pack_name="procurement_demo", pack_version=3, pack_digest=digest, defs=defs,
            org_id=ORG_ID, instance_id=self.inst, task_id=self.task_id, seat_name=SEAT, seat_version=1,
            seat_doc=defs["Seat"][SEAT], workflow_name="quick_quote", template=tpl, participant_role="requester",
            person_id="faisal", seat_limits=defs["Seat"][SEAT]["spec"]["limits"],
        )
        await self.conn.execute(
            "insert into work.tasks (id, instance_id, kind, template, skill, work_type, verifier, state, contract,"
            " contract_hash, max_attempts, fencing_token, attempts_used)"
            " values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema', 'RUNNING',"
            " %s, %s, 4, 0, 0)",
            (self.task_id, self.inst, json.dumps(self.contract), self.contract["contract_hash"]),
        )
        self.artifact_id = ids.new_artifact_id()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'brief', '', 'Brief', 'draft', 0)",
            (self.artifact_id, self.inst),
        )

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)
        shutil.rmtree(self.packs, ignore_errors=True)

    async def attempt(self, n: int, observations: list[dict]) -> str:
        attempt_id = ids.new_attempt_id()
        await self.conn.execute(
            "update work.tasks set fencing_token = %s, attempts_used = %s, state = 'RUNNING' where id = %s",
            (n, n, self.task_id),
        )
        await self.conn.execute(
            "insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd, worker_id,"
            " lease_expires_at, tool_observations)"
            " values (%s, %s, %s, %s, 'CLAIMED', 1.0, 'w-verify', now() + interval '5 minutes', %s)",
            (attempt_id, self.task_id, n, n, json.dumps(observations)),
        )
        return attempt_id

    async def save_and_submit(self, attempt_id: str, n: int, content: dict) -> dict:
        content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash, produced_by_kind,"
            " produced_by, inputs, sources) values (%s, %s, %s, %s, 'attempt', %s, '[]', '[]')",
            (self.artifact_id, n, json.dumps(content), content_hash, attempt_id),
        )
        await self.conn.execute("update work.artifacts set latest_version = %s where id = %s", (n, self.artifact_id))
        async with self.conn.transaction():
            return await submit_result(
                self.conn, org=ORG, org_id=ORG_ID, attempt_id=attempt_id, worker_id="w-verify", fencing_token=n,
                result={
                    "attempt_id": attempt_id,
                    "contract_id": self.contract["contract_id"],
                    "status": "completed",
                    "summary": "Brief saved.",
                    "output_artifact_refs": [
                        {"artifact_id": self.artifact_id, "version": n, "content_hash": content_hash}
                    ],
                    "input_versions": {},
                },
                packs_dir=self.packs,
            )

    async def one(self, query: str, *args) -> object:
        cur = await self.conn.execute(query, args)
        row = await cur.fetchone()
        return row[0] if row else None

    async def test_rework_findings_reach_the_next_attempt_which_passes(self) -> None:
        browsed = [{"tool": "browse_categories", "args": {"query": "cleaning trolley"}, "at": "2026-10-21T09:00:00Z",
                    "untrusted": True, "receipt_ref": "tp_cat1",
                    "content": {"items": [{"id": "CAT-JAN-EQ", "name": "Janitorial equipment"}]}}]
        first = await self.attempt(1, browsed)
        response = await self.save_and_submit(first, 1, _brief(delivery_date="2026-10-22", category="CAT-XYZ"))

        self.assertEqual(response["verdict"], "REWORK")
        self.assertEqual(response["task_state"], "READY")
        findings = [
            "category: not returned by browse_categories for this task",
            "delivery_date: must be at least three days from today",
        ]
        self.assertEqual(response["verifier"], {"name": "brief_schema", "verdict": "REWORK", "findings": findings})
        stamped = await self.one(
            "select verification from work.artifact_versions where artifact_id = %s and version = 1", self.artifact_id
        )
        self.assertEqual(stamped, {"verifier": "brief_schema", "verdict": "REWORK", "findings": findings})
        event = await self.one(
            "select jsonb_build_object('audience', audience, 'data', data) from evidence.outbox"
            " where instance_id = %s and event_type = 'verification.completed'",
            self.inst,
        )
        self.assertEqual(event["audience"], {"roles": ["requester"]})
        self.assertEqual(event["data"]["verdict"], "REWORK")
        self.assertEqual(event["data"]["task_id"], self.task_id)

        # The category lookup came from attempt 1; it still counts for attempt 2 of the same Task.
        second = await self.attempt(2, [])
        gate = await evaluate_claimed_fence(
            self.conn, org_id=ORG_ID, attempt_id=second, worker_id="w-verify", fencing_token=2
        )
        envelope = await assemble_context(self.conn, org=ORG, gate=gate, refresh_reason="start", packs_dir=self.packs)
        self.assertEqual(envelope["rework"], {"verifier": "brief_schema", "findings": findings})
        _schema_validator("context-envelope.schema.json").validate(envelope)

        response = await self.save_and_submit(second, 2, _brief())
        self.assertEqual(response["verdict"], "ACCEPTED")
        self.assertEqual(response["task_state"], "COMPLETED")
        self.assertEqual(
            await self.one("select verification->>'verdict' from work.artifact_versions"
                           " where artifact_id = %s and version = 2", self.artifact_id),
            "PASS",
        )

    async def test_first_attempt_has_no_rework(self) -> None:
        first = await self.attempt(1, [])
        gate = await evaluate_claimed_fence(
            self.conn, org_id=ORG_ID, attempt_id=first, worker_id="w-verify", fencing_token=1
        )
        envelope = await assemble_context(self.conn, org=ORG, gate=gate, refresh_reason="start", packs_dir=self.packs)
        self.assertNotIn("rework", envelope)


if __name__ == "__main__":
    unittest.main()
