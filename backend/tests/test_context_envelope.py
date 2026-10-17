"""M1-BE-06: context envelope assembly, visibility and assembleContext route."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from aos.api import create_app
from aos.kernel import ids
from aos.kernel.auth import issue_worker_token
from aos.kernel.contracts import _canonical_json, contract_hash
from aos.kernel.org import load_org
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"
PLANT_PRICE = "SAR 88888.01"
DISTINCT_QQ2_TITLE = "QQ2-LEAK-TITLE-XYZZY"
CONTRACTS = REPO / "docs" / "specs" / "contracts"
SCHEMAS = CONTRACTS / "schemas"
EXAMPLES = CONTRACTS / "examples"


def _schema_validator(name: str) -> Draft202012Validator:
    schemas = {p.name: json.loads(p.read_text()) for p in SCHEMAS.glob("*.schema.json")}
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return Draft202012Validator(schemas[name], registry=registry)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ContextEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-context-"))
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

    def worker_auth(self, worker_id: str = "worker-ctx-1") -> dict:
        token = issue_worker_token(ORG.organization.id, worker_id, self.settings.session_secret)
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

        async def _seats() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(cls.db)) as conn:
                async with conn.transaction():
                    await insert_seats_for_published_pack(
                        conn, org=ORG, org_id=ORG.organization.id, pack_version_id=cls.version_id
                    )

        asyncio.run(_seats())
        seat = cls.client.get(f"/api/console/seats/{SEAT}", headers=cls._auth("platform_admin")).json()
        rv = seat["record_version"]
        if seat.get("state") == "DRAFT":
            r = cls.client.post(
                f"/api/console/seats/{SEAT}/configure",
                headers=cls._auth("platform_admin"),
                json={"version": 1, "expected_version": rv},
            )
            assert r.status_code == 200, r.text
            rv = r.json()["record_version"]
        _pg.admin_sql(
            cls.db,
            f"""
            update registry.seats set state = 'APPROVED', record_version = {rv}
            where org_id = 'org_demo' and name = '{SEAT}' and version = 1;
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_ctx_refusals', 'org_demo', '{SEAT}', 1, 'refusals', 'fake', 'passed', 4, 4),
              ('ev_ctx_dry_run', 'org_demo', '{SEAT}', 1, 'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )
        r = cls.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=cls._auth("head_of_procurement"),
            json={"version": 1, "expected_version": rv},
        )
        assert r.status_code == 200, r.text

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            f"""
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.pending_items;
            delete from work.artifact_versions;
            delete from work.artifacts;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            delete from gov.decision_records where event in ('admission.denied', 'context.denied');
            update registry.seats set state = 'ACTIVE'
            where org_id = 'org_demo' and name = '{SEAT}' and version = 1;
            """,
        )

    def _start(self, person: str = "faisal", message: str = "Context test job") -> str:
        r = self.client.post(
            "/api/instances",
            headers={**self._auth(person), "Idempotency-Key": str(uuid.uuid4())},
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": message},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["instance_id"]

    def _claim(self, lanes: list[str] | None = None) -> dict:
        lanes = lanes or ["assist", "task"]
        r = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth(),
            json={"worker_id": "worker-ctx-1", "lanes": lanes},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _assemble(self, attempt_id: str, token: int, reason: str = "start") -> dict:
        r = self.client.post(
            f"/api/worker/attempts/{attempt_id}/context",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(token)},
            json={"reason": reason},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _set_contract_on_attempt(self, attempt: dict, contract: dict) -> None:
        contract = dict(contract)
        contract["contract_hash"] = contract_hash(contract)
        payload = json.dumps(contract).replace("'", "''")
        _pg.admin_sql(
            self.db,
            f"""
            update work.tasks set contract = '{payload}'::jsonb,
                contract_hash = '{contract["contract_hash"]}'
            where id = '{attempt["task_id"]}';
            """,
        )

    def test_envelope_validates_against_schema(self) -> None:
        self._start()
        attempt = self._claim()
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        validator = _schema_validator("context-envelope.schema.json")
        validator.validate(envelope)

    def test_shareable_ceiling_drops_budget_guidance(self) -> None:
        inst = self._start("faisal")
        brief_id = ids.new_artifact_id()
        content = {
            "title": "Trolleys",
            "category": "janitorial_equipment",
            "quantity": 40,
            "specification": "Spec",
            "delivery_date": "2026-11-20",
            "delivery_site": "Mall A",
            "budget_guidance": "SAR 50000",
        }
        full_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)
            values ('{brief_id}', '{inst}', 'brief', 'main', 'Brief', 'final', 1);
            insert into work.artifact_versions (
              artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources
            ) values ('{brief_id}', 1, '{json.dumps(content)}'::jsonb, '{full_hash}', 'person', 'faisal', '[]', '[]');
            insert into work.participants (instance_id, role, person_id, bound_by)
            values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;
            """,
        )
        contract = json.loads((EXAMPLES / "task-contract.rfq_draft.json").read_text())
        contract["instance_id"] = inst
        contract["immutable_input_refs"] = [
            {
                "artifact_type": "brief",
                "artifact_id": brief_id,
                "version": 1,
                "content_hash": full_hash,
            }
        ]
        contract["on_behalf_of"] = {"role": "buyer", "person_id": "noura"}
        task_id = ids.new_task_id()
        attempt_id = ids.new_attempt_id()
        contract["task_id"] = task_id
        contract["contract_hash"] = contract_hash(contract)
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash, max_attempts, fencing_token
            ) values (
              '{task_id}', '{inst}', 'task', 'rfq_draft', 'rfq_authoring', 'document_draft', null, 'RUNNING',
              '{json.dumps(contract)}'::jsonb, '{contract["contract_hash"]}', 3, 1
            );
            insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd)
            values ('{attempt_id}', '{task_id}', 1, 2, 'ADMITTED', 1.5);
            update work.tasks set fencing_token = 2, attempts_used = 1 where id = '{task_id}';
            """,
        )
        attempt = self._claim(lanes=["task"])
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        brief = next(a for a in envelope["artifacts"] if a["artifact_type"] == "brief")
        self.assertNotIn("budget_guidance", brief["content"])
        self.assertNotIn("SAR 50000", json.dumps(brief))
        fields = {r["field"] for r in envelope["redactions"]}
        self.assertIn("budget_guidance", fields)
        bg = next(r for r in envelope["redactions"] if r["field"] == "budget_guidance")
        self.assertIn("artifact_id", bg)
        self.assertEqual(bg["artifact_id"], brief["artifact_id"])

    def _insert_comparison(
        self, instance_id: str, *, plant: str = PLANT_PRICE, art_id: str | None = None
    ) -> tuple[str, str]:
        art_id = art_id or ids.new_artifact_id()
        content = {
            "rows": [
                {
                    "rank": 1,
                    "supplier": "A",
                    "unit_price": plant,
                    "total": plant,
                    "lead_time_days": 5,
                    "warranty_months": 12,
                    "score": 90,
                }
            ]
        }
        full_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
        verification = json.dumps(
            {"verifier": "score_recompute", "verdict": "pass", "findings": [f"Line total {plant} verified"]}
        )
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)
            values ('{art_id}', '{instance_id}', 'comparison', 'main', 'Comparison', 'draft', 1);
            insert into work.artifact_versions (
              artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources, verification
            ) values (
              '{art_id}', 1, '{json.dumps(content)}'::jsonb, '{full_hash}', 'person', 'noura',
              '[]', '[]', '{verification}'::jsonb
            );
            """,
        )
        return art_id, full_hash

    def _quote_comparison_contract(self, inst: str, *, person: str = "faisal", role: str = "requester") -> dict:
        contract = json.loads((EXAMPLES / "task-contract.rfq_draft.json").read_text())
        contract["instance_id"] = inst
        contract["skill"] = {"name": "quote_comparison", "version": 1, "instructions_sha256": "a" * 64}
        contract["on_behalf_of"] = {"role": role, "person_id": person}
        contract["permission_scope"]["classification_ceiling"] = "internal"
        contract["immutable_input_refs"] = []
        return contract

    def test_requester_quote_comparison_leak_and_redactions(self) -> None:
        inst = self._start("faisal")
        self._insert_comparison(inst)
        _pg.admin_sql(
            self.db,
            f"""
            update work.instances set attributes = attributes || '{{"po_amount": 99999.01}}'::jsonb where id = '{inst}';
            """,
        )
        attempt = self._claim()
        self._set_contract_on_attempt(attempt, self._quote_comparison_contract(inst))
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        dumped = json.dumps(envelope)
        self.assertNotIn(PLANT_PRICE, dumped)
        self.assertNotIn("99999.01", dumped)
        self.assertIn("job_snapshot", envelope["resolvers"])
        redacted_fields = {r["field"] for r in envelope["redactions"]}
        self.assertIn("unit_price", redacted_fields)
        self.assertIn("total", redacted_fields)
        self.assertIn("attributes.po_amount", redacted_fields)
        self.assertTrue(any(r["field"] == "unit_price" and r.get("artifact_id") for r in envelope["redactions"]))

    def test_request_intake_recent_messages_visibility_and_seat_author(self) -> None:
        inst = self._start("faisal", "Need trolleys")
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.turns (
              id, instance_id, seq, author_kind, author_id, audience_roles, blocks, client_turn_id
            ) values (
              '{ids.new_turn_id()}', '{inst}', 98, 'person', 'noura', array['buyer']::text[],
              '[{{"kind":"text","text":"Buyer-only {PLANT_PRICE}"}}]'::jsonb, 'leak-buyer-turn'
            );
            insert into work.turns (
              id, instance_id, seq, author_kind, author_id, audience_roles, blocks, client_turn_id
            ) values (
              '{ids.new_turn_id()}', '{inst}', 99, 'seat', '{SEAT}', null,
              '[{{"kind":"text","text":"Agent reply"}}]'::jsonb, 'leak-seat-turn'
            );
            """,
        )
        attempt = self._claim()
        contract = self._quote_comparison_contract(inst)
        contract["skill"] = {"name": "request_intake", "version": 1, "instructions_sha256": "a" * 64}
        self._set_contract_on_attempt(attempt, contract)
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        self.assertIn("recent_messages", envelope["resolvers"])
        messages = envelope["resolvers"]["recent_messages"]
        texts = [m["text"] for m in messages]
        authors = [m["author"] for m in messages]
        self.assertNotIn(PLANT_PRICE, json.dumps(messages))
        self.assertFalse(any(PLANT_PRICE in t for t in texts))
        self.assertTrue(any("Need trolleys" in t for t in texts))
        self.assertIn("Sourcing Agent", authors)

    def test_resolve_pending_items_filters_by_viewer(self) -> None:
        inst = self._start("faisal")
        pend_faisal = ids.new_pending_id()
        pend_khalid = ids.new_pending_id()
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.pending_items (
              id, instance_id, kind, title, detail, for_role, for_person_id, options, status
            ) values
              ('{pend_khalid}', '{inst}', 'approval', 'Approver {PLANT_PRICE}', 'secret', 'procurement_approver', 'khalid', '[]', 'open'),
              ('{pend_faisal}', '{inst}', 'question', 'Faisal {PLANT_PRICE}', 'secret', 'requester', 'faisal', '[]', 'open');
            """,
        )

        async def _run() -> list[dict]:
            from aos.kernel.context import _resolve_pending_items

            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                return await _resolve_pending_items(
                    conn, inst, person_id="faisal", viewer_roles=["requester"]
                )

        items = asyncio.run(_run())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], pend_faisal)
        self.assertIn(PLANT_PRICE, items[0]["summary"])
        self.assertNotIn("secret", json.dumps(items))

    def test_undeclared_instance_attribute_is_redacted(self) -> None:
        inst = self._start("faisal")
        _pg.admin_sql(
            self.db,
            f"update work.instances set attributes = '{{\"undeclared_metric\": 42}}'::jsonb where id = '{inst}';",
        )
        attempt = self._claim()
        contract = self._quote_comparison_contract(inst)
        contract["skill"] = {"name": "request_intake", "version": 1, "instructions_sha256": "a" * 64}
        self._set_contract_on_attempt(attempt, contract)
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        snap = envelope["resolvers"]["job_snapshot"]
        self.assertNotIn("undeclared_metric", snap["attributes"])
        self.assertIn("attributes.undeclared_metric", {r["field"] for r in envelope["redactions"]})

    def test_two_quotes_in_quote_comparison_envelope(self) -> None:
        inst = self._start("faisal")
        for key in ("sup_a", "sup_b"):
            qid = ids.new_artifact_id()
            content = {"supplier": key, "received_at": "2026-10-01", "unit_price": "1", "lead_time_days": 3}
            h = hashlib.sha256(_canonical_json(content)).hexdigest()
            _pg.admin_sql(
                self.db,
                f"""
                insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)
                values ('{qid}', '{inst}', 'quote', '{key}', 'Quote {key}', 'final', 1);
                insert into work.artifact_versions (
                  artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources
                ) values ('{qid}', 1, '{json.dumps(content)}'::jsonb, '{h}', 'person', 'noura', '[]', '[]');
                """,
            )
        contract = json.loads((EXAMPLES / "task-contract.rfq_draft.json").read_text())
        contract["instance_id"] = inst
        contract["skill"] = {"name": "quote_comparison", "version": 1, "instructions_sha256": "b" * 64}
        contract["on_behalf_of"] = {"role": "buyer", "person_id": "noura"}
        contract["immutable_input_refs"] = []
        _pg.admin_sql(
            self.db,
            f"insert into work.participants (instance_id, role, person_id, bound_by)"
            f" values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;",
        )
        attempt = self._claim()
        self._set_contract_on_attempt(attempt, contract)
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        quotes = [a for a in envelope["artifacts"] if a["artifact_type"] == "quote"]
        self.assertEqual(len(quotes), 2)

    def test_redacted_artifact_uses_projected_content_hash(self) -> None:
        inst = self._start("faisal")
        art_id, stored = self._insert_comparison(inst)
        contract = json.loads((EXAMPLES / "task-contract.rfq_draft.json").read_text())
        contract["instance_id"] = inst
        contract["skill"] = {"name": "quote_comparison", "version": 1, "instructions_sha256": "c" * 64}
        contract["on_behalf_of"] = {"role": "requester", "person_id": "faisal"}
        contract["immutable_input_refs"] = []
        attempt = self._claim()
        self._set_contract_on_attempt(attempt, contract)
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        item = next(a for a in envelope["artifacts"] if a["artifact_id"] == art_id)
        self.assertNotEqual(item["content_hash"], stored)
        dumped = json.dumps(envelope)
        self.assertNotIn(stored, dumped)
        prov = next(p for p in envelope["provenance"] if art_id in p["source_ref"])
        self.assertEqual(prov["sha256"], item["content_hash"])

    def test_non_participant_on_behalf_of_is_403_with_decision(self) -> None:
        self._start("faisal")
        attempt = self._claim()
        contract = dict(attempt["contract"])
        contract["on_behalf_of"] = {"role": "buyer", "person_id": "noura"}
        self._set_contract_on_attempt(attempt, contract)
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/context",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
            json={"reason": "start"},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")
        self.assertIn("decision_id", r.json())
        dr = _pg.admin_sql(
            self.db,
            "select event, value, artifact_ref from gov.decision_records order by at desc limit 1;",
        ).stdout
        self.assertIn("context.denied", dr)

    def test_c07_natural_cross_job_turn_does_not_leak(self) -> None:
        inst1 = self._start("faisal", "Tell me about the other job")
        inst2 = self._start("faisal_manager", DISTINCT_QQ2_TITLE)
        faisal_on_2 = _pg.admin_sql(
            self.db,
            f"select count(*) from work.participants where instance_id = '{inst2}' and person_id = 'faisal';",
        ).stdout.strip()
        self.assertEqual(faisal_on_2, "0")
        self._insert_comparison(inst2, plant=PLANT_PRICE)
        _pg.admin_sql(
            self.db,
            f"update work.instances set title = '{DISTINCT_QQ2_TITLE}' where id = '{inst2}';",
        )
        self.client.post(
            f"/api/instances/{inst1}/turns",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": f"What is the price on {inst2}?"},
        )
        attempt = self._claim(lanes=["assist"])
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        self.assertEqual(envelope["ids"]["instance_id"], inst1)
        dumped = json.dumps(envelope)
        self.assertNotIn(PLANT_PRICE, dumped)
        self.assertNotIn(DISTINCT_QQ2_TITLE, dumped)

    def test_c07_tampered_immutable_input_ref_records_decision_without_other_job_id(self) -> None:
        inst1 = self._start("faisal")
        inst2 = self._start("faisal_manager")
        faisal_on_2 = _pg.admin_sql(
            self.db,
            f"select count(*) from work.participants where instance_id = '{inst2}' and person_id = 'faisal';",
        ).stdout.strip()
        self.assertEqual(faisal_on_2, "0")
        art2, _ = self._insert_comparison(inst2)
        contract = json.loads((EXAMPLES / "task-contract.rfq_draft.json").read_text())
        contract["instance_id"] = inst1
        contract["skill"] = {"name": "quote_comparison", "version": 1, "instructions_sha256": "d" * 64}
        contract["on_behalf_of"] = {"role": "requester", "person_id": "faisal"}
        contract["immutable_input_refs"] = [
            {"artifact_type": "comparison", "artifact_id": art2, "version": 1, "content_hash": "deadbeef" * 8}
        ]
        attempt = self._claim()
        self._set_contract_on_attempt(attempt, contract)
        envelope = self._assemble(attempt["attempt_id"], attempt["fencing_token"])
        self.assertNotIn(PLANT_PRICE, json.dumps(envelope))
        dr = _pg.admin_sql(
            self.db,
            f"select subject_id, artifact_ref::text from gov.decision_records"
            f" where subject_id = '{inst1}' and event = 'context.denied' order by at desc limit 1;",
        ).stdout
        self.assertIn(inst1, dr)
        self.assertNotIn(inst2, dr)
        self.assertNotIn(art2, dr)
        audit = _pg.admin_sql(
            self.db,
            "select data::text from evidence.audit_events order by seq desc limit 1;",
        ).stdout
        self.assertIn(art2, audit)
        self.assertIn(inst2, audit)

    def test_context_too_large_returns_413(self) -> None:
        self._start()
        attempt = self._claim()
        import aos.kernel.context as ctx_mod

        with patch.object(ctx_mod, "MAX_ENVELOPE_BYTES", 200):
            r = self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/context",
                headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
                json={"reason": "start"},
            )
        self.assertEqual(r.status_code, 413, r.text)
        self.assertEqual(r.json()["code"], "context_too_large")

    def test_fenced_assemble_context_commits_attempt_fenced(self) -> None:
        self._start()
        attempt = self._claim()
        old = attempt["fencing_token"]
        _pg.admin_sql(
            self.db,
            f"update work.tasks set fencing_token = fencing_token + 1 where id = '{attempt['task_id']}';",
        )
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/context",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(old)},
            json={"reason": "start"},
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "fenced")
        count = _pg.admin_sql(
            self.db,
            f"select count(*) from evidence.execution_events"
            f" where attempt_id = '{attempt['attempt_id']}' and event_type = 'AttemptFenced';",
        ).stdout.strip()
        self.assertEqual(count, "1")


if __name__ == "__main__":
    unittest.main()
