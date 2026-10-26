"""Rule verifiers and the REWORK loop (M2-AG-03): brief_schema, sources_cited, leak_check."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from aos.kernel import clock, contracts, ids, verify
from aos.kernel.context import assemble_context
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import seed_sql
from aos.kernel.settings import REPO
from aos.kernel.worker_fence import evaluate_claimed_fence
from aos.kernel.worker_submit import submit_result
from aos.registry.kinds import ArtifactTypeSpec
from aos.verifiers import brief_schema, leak_check, sources_cited

from . import _pg
from .test_context_envelope import _schema_validator
from .test_decisions import ORG, ORG_ID, SEAT, _insert_instance, _sync_published
from .test_task_contracts import _defs, _templates

TODAY = date(2026, 10, 21)


def _brief(**overrides) -> dict:
    content = {
        "title": "40 cleaning trolleys for Mall A",
        "category": "CAT-JAN-EQ",
        "quantity": 40,
        "specification": "Three-bucket trolley, 120 L, lockable caddy",
        "delivery_date": "2026-11-20",
        "delivery_site": "Mall A loading bay",
        "budget_guidance": 15000,
    }
    content.update(overrides)
    return {k: v for k, v in content.items() if v is not None}


def _row(rank: int, sid: str, score: float, sources: list | None = None) -> dict:
    return {"rank": rank, "supplier": f"Supplier {sid}", "supplier_id": sid, "score": score,
            "sources": ["tp_search"] if sources is None else sources}


class BriefSchemaRules(unittest.TestCase):
    def check(self, content: dict, categories: set[str] | None = None) -> list[str]:
        return brief_schema.check_brief(content, today=TODAY, category_ids=categories or {"CAT-JAN-EQ"})

    def test_complete_brief_passes(self) -> None:
        self.assertEqual(self.check(_brief()), [])

    def test_one_finding_per_missing_field(self) -> None:
        findings = self.check(_brief(title="", delivery_site=None, quantity=None))
        self.assertEqual(findings, ["title is missing.", "delivery_site is missing.", "quantity is missing."])

    def test_quantity_must_be_a_positive_whole_number(self) -> None:
        for bad in (0, -2, 2.5, "40", True):
            with self.subTest(quantity=bad):
                self.assertEqual(self.check(_brief(quantity=bad)), ["quantity must be a whole number above 0."])

    def test_delivery_date_at_least_three_days_out(self) -> None:
        self.assertEqual(self.check(_brief(delivery_date="2026-10-24")), [])
        self.assertEqual(
            self.check(_brief(delivery_date="2026-10-23")),
            ["delivery_date must be 2026-10-24 or later (3 days from today)."],
        )
        self.assertEqual(self.check(_brief(delivery_date="next week")),
                         ["delivery_date must be a date like 2026-11-20."])

    def test_category_must_come_from_this_tasks_lookups(self) -> None:
        self.assertEqual(self.check(_brief(), categories={"CAT-FAC-SVC"}),
                         ["category must be an id that browse_categories returned in this Task."])

    def test_category_ids_read_from_observations(self) -> None:
        obs = [
            {"tool": "browse_categories", "content": {"items": [{"id": "CAT-JAN-EQ", "name": "Janitorial"}]}},
            {"tool": "search_suppliers", "content": {"items": [{"id": "SUP-1"}]}},
        ]
        self.assertEqual(brief_schema.category_ids(obs), {"CAT-JAN-EQ"})


class SourcesCitedRules(unittest.TestCase):
    def check(self, rows: list[dict]) -> list[str]:
        return sources_cited.check_rows(rows, receipt_refs={"tp_search", "tp_hist"}, searched_ids={"S1", "S2", "S3"})

    def test_ranked_cited_list_passes(self) -> None:
        self.assertEqual(self.check([_row(1, "S1", 0.9, ["tp_search", "tp_hist"]), _row(2, "S2", 0.7),
                                     _row(3, "S3", 0.7)]), [])

    def test_row_without_sources(self) -> None:
        self.assertEqual(self.check([_row(1, "S1", 0.9, [])]), ["Row 1 (Supplier S1) cites no source."])

    def test_source_that_is_not_this_tasks_receipt(self) -> None:
        self.assertEqual(
            self.check([_row(1, "S1", 0.9, ["tp_search", "tp_other"])]),
            ["Row 1 (Supplier S1) cites 1 source(s) that are not receipts from this Task's tool calls."],
        )

    def test_supplier_not_returned_by_a_search(self) -> None:
        self.assertEqual(
            self.check([_row(1, "S9", 0.9)]),
            ["Row 1 (Supplier S9) has a supplier_id that no search_suppliers call in this Task returned."],
        )

    def test_ranks_without_gaps_in_score_order(self) -> None:
        self.assertEqual(self.check([_row(1, "S1", 0.9), _row(3, "S2", 0.8)]),
                         ["Ranks must run 1 to 2 with no gaps or repeats."])
        self.assertEqual(self.check([_row(1, "S1", 0.5), _row(2, "S2", 0.8)]),
                         ["Rank order must follow score, highest first."])

    def test_empty_list(self) -> None:
        self.assertEqual(self.check([]), ["The list has no rows."])


class LeakCheckRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        defs, _ = _defs()
        cls.specs = {name: ArtifactTypeSpec.model_validate(doc["spec"]) for name, doc in defs["ArtifactType"].items()}

    def findings(self, body: str, protected_content: dict, protected_type: str = "brief") -> list[str]:
        protected = leak_check.protected_values(protected_type, protected_content, self.specs[protected_type])
        email = {"supplier_id": "SUP-10482", "to": "sales@najd.example", "subject": "Request for quotation",
                 "body": body}
        fields = leak_check.shareable_text(email, self.specs["rfq_email"])
        return leak_check.check_output("rfq_email", fields, protected)

    def test_numbers_normalise(self) -> None:
        for text in ("40,000", "SAR 40000", "40k", "SAR40,000.00", "40 000", "budget: 40K."):
            with self.subTest(text=text):
                self.assertIn(40000.0, leak_check.numbers_in(text))
        self.assertNotIn(40000.0, leak_check.numbers_in("40kg"))

    def test_budget_in_body_is_caught_and_named_not_quoted(self) -> None:
        findings = self.findings("Please quote; we expect around SAR 15,000 in total.", _brief())
        self.assertEqual(findings, ["rfq_email.body contains the value of brief.budget_guidance."])
        self.assertNotIn("15", " ".join(findings))

    def test_shareable_brief_fields_may_appear(self) -> None:
        body = ("We invite you to quote for 40 three-bucket cleaning trolleys (120 L, lockable caddy), delivered to "
                "the Mall A loading bay by 20 November 2026.")
        self.assertEqual(self.findings(body, _brief()), [])

    def test_restricted_quote_figures_are_caught(self) -> None:
        content = {"supplier": "Najd Supplies", "unit_price": "SAR 1,240", "total": 49600, "lead_time_days": 10,
                   "received_at": "2026-10-25T09:00:00Z"}
        self.assertEqual(
            self.findings("Another bidder offered 49,600 for the lot, or 1240 a unit.", content, "quote"),
            ["rfq_email.body contains the value of quote.total.", "rfq_email.body contains the value of quote.unit_price."],
        )

    def test_protected_text_matches_case_insensitively(self) -> None:
        spec = ArtifactTypeSpec.model_validate({
            "fields": {"note": {"type": "string", "classification": "internal"}},
            "view": {"type": "document"},
            "visibility": {"buyer": "all"},
        })
        protected = leak_check.protected_values("memo", {"note": "Prefer Gulf Janitorial"}, spec)
        fields = {"body": ["We  PREFER gulf janitorial this time."]}
        self.assertEqual(leak_check.check_output("rfq_email", fields, protected),
                         ["rfq_email.body contains the value of memo.note."])

    def test_type_default_classification_is_not_a_secret(self) -> None:
        supplier_list = {"rows": [_row(1, "SUP-10482", 0.92)]}
        self.assertEqual(self.findings("Dear Supplier SUP-10482, rank 1.", supplier_list, "supplier_list"), [])


class VerifierRegistry(unittest.IsolatedAsyncioTestCase):
    async def run_impl(self, impl: str) -> tuple[str, list[str]]:
        defs = {"Verifier": {"v": {"spec": {"implementation": impl}}}}
        return await verify.run_task_verifier(None, verifier_name="v", defs=defs, gate=None, result={})  # type: ignore[arg-type]

    async def test_only_shipped_verifier_modules_load(self) -> None:
        self.assertIs(verify._handler_for("aos.verifiers.brief_schema"), brief_schema.verify)
        for impl in ("os.path", "aos.verifiers._records", "aos.verifiers.nope", "aos.kernel.verify"):
            with self.subTest(impl=impl):
                verdict, findings = await self.run_impl(impl)
                self.assertEqual(verdict, "FAIL", "a verifier that can't run never passes work")
                self.assertIn("no implementation", findings[0])


@unittest.skipUnless(_pg.available(), "no local Postgres")
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
            "delivery_date must be 2026-10-24 or later (3 days from today).",
            "category must be an id that browse_categories returned in this Task.",
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
