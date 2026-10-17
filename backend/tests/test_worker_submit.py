"""M1-BE-05-B: postAttemptEvents, saveDraft, askQuestions, submitResult."""

from __future__ import annotations

import asyncio
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import psycopg

from aos.kernel import worker_submit

from . import _pg
from .test_worker_api import ORG, WorkerHarness


def _valid_brief() -> dict:
    return {
        "title": "Office chairs",
        "category": "furniture",
        "quantity": 10,
        "specification": "Ergonomic",
        "delivery_date": "2026-12-01",
        "delivery_site": "Riyadh HQ",
    }


def _agent_result(attempt: dict, *, blocks: list | None = None, consumed: dict | None = None) -> dict:
    body: dict = {
        "schema_version": "aos.agent_result/1",
        "contract_id": attempt["contract"]["contract_id"],
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "output_artifact_refs": [],
        "evidence_refs": [],
        "input_versions": {},
        "consumed_budget": consumed
        or {
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "time_s": 0.0,
            "steps": 0,
            "actions": 0,
        },
        "summary": "Replied in chat.",
        "reply_blocks": blocks or [{"kind": "text", "text": "Hello from the agent."}],
    }
    return body


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerSubmitTests(WorkerHarness):
    def _worker_headers(self, attempt: dict, worker_id: str = "worker-test-1") -> dict:
        return {
            **self.worker_auth(worker_id),
            "X-AOS-Fencing-Token": str(attempt["fencing_token"]),
        }

    def _save_brief(self, attempt: dict, *, missing_title: bool = False) -> dict:
        content = _valid_brief()
        if missing_title:
            del content["title"]
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/drafts",
            headers=self._worker_headers(attempt),
            json={"artifact_type": "brief", "content": content, "inputs": []},
        )
        return r

    def test_save_draft_wrong_artifact_type_is_403(self) -> None:
        self._start_job()
        attempt = self._claim()
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/drafts",
            headers=self._worker_headers(attempt),
            json={"artifact_type": "comparison", "content": {"rows": []}, "inputs": []},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_save_draft_same_key_without_artifact_id_versions_one_artifact(self) -> None:
        self._start_job()
        attempt = self._claim()
        payload = {
            "artifact_type": "brief",
            "key": "intake",
            "content": _valid_brief(),
            "inputs": [],
        }
        r1 = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/drafts",
            headers=self._worker_headers(attempt),
            json=payload,
        )
        self.assertEqual(r1.status_code, 201, r1.text)
        self.assertEqual(r1.json()["version"], 1)
        aid = r1.json()["artifact_id"]
        payload["content"] = {**_valid_brief(), "specification": "Updated spec"}
        r2 = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/drafts",
            headers=self._worker_headers(attempt),
            json=payload,
        )
        self.assertEqual(r2.status_code, 201, r2.text)
        self.assertEqual(r2.json()["version"], 2)
        self.assertEqual(r2.json()["artifact_id"], aid)
        count = _pg.admin_sql(
            self.db,
            f"select count(*) from work.artifacts where instance_id = ("
            f" select instance_id from work.tasks where id = '{attempt['task_id']}')"
            f" and artifact_type = 'brief' and key = 'intake';",
        ).stdout.strip()
        self.assertEqual(count, "1")

    def test_save_draft_missing_required_field_is_422(self) -> None:
        self._start_job()
        attempt = self._claim()
        r = self._save_brief(attempt, missing_title=True)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["code"], "validation_failed")
        self.assertTrue(r.json().get("errors"))

    def test_budget_cross_via_events_ends_attempt_and_fences_next_call(self) -> None:
        self._start_job()
        attempt = self._claim()
        budget = attempt["contract"]["budget"]
        over_tokens = int(budget["tokens"]) + 100
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/events",
            headers=self._worker_headers(attempt),
            json={
                "events": [
                    {
                        "event_type": "ModelInvoked",
                        "redacted_summary": "model step",
                        "attributes": {
                            "tokens_in": over_tokens,
                            "tokens_out": 0,
                            "cost_usd": 0.01,
                        },
                    }
                ],
            },
        )
        self.assertEqual(r.status_code, 202, r.text)
        state = _pg.admin_sql(
            self.db,
            f"select state, outcome from work.attempts where id = '{attempt['attempt_id']}';",
        ).stdout.strip()
        self.assertIn("ENDED", state)
        self.assertIn("failed", state)
        be = _pg.admin_sql(
            self.db,
            f"select count(*) from evidence.execution_events"
            f" where attempt_id = '{attempt['attempt_id']}' and event_type = 'BudgetExceeded';",
        ).stdout.strip()
        self.assertEqual(be, "1")
        hb = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/heartbeat",
            headers=self._worker_headers(attempt),
        )
        self.assertEqual(hb.status_code, 409, hb.text)

    def test_agent_turn_uses_seat_display_name_from_registry(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit",
            headers=self._worker_headers(attempt),
            json=body,
        )
        self.assertEqual(r.status_code, 200, r.text)
        display = _pg.admin_sql(
            self.db,
            "select display_name from registry.seats"
            " where org_id = 'org_demo' and name = 'seat_sourcing_poc' and version = 1;",
        ).stdout.strip()
        self.assertEqual(display, "Sourcing Agent")
        turn_name = _pg.admin_sql(
            self.db,
            f"select data->'turn'->'author'->>'name' from evidence.outbox"
            f" where event_type = 'agent.message.completed'"
            f" order by seq desc limit 1;",
        ).stdout.strip()
        self.assertEqual(turn_name, display)

    def test_happy_assist_submit_leaves_task_waiting_input(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit",
            headers=self._worker_headers(attempt),
            json=body,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["verdict"], "ACCEPTED")
        self.assertEqual(r.json()["task_state"], "WAITING_INPUT")
        task_state = _pg.admin_sql(
            self.db,
            f"select state from work.tasks where id = '{attempt['task_id']}';",
        ).stdout.strip()
        self.assertEqual(task_state, "WAITING_INPUT")

    def test_submit_stale_input_versions_returns_stale_verdict(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        body["input_versions"] = {"brief": 999}
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit",
            headers=self._worker_headers(attempt),
            json=body,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["verdict"], "STALE")
        self.assertTrue(r.json().get("next_attempt"))
        task_state = _pg.admin_sql(
            self.db,
            f"select state from work.tasks where id = '{attempt['task_id']}';",
        ).stdout.strip()
        self.assertEqual(task_state, "READY")

    def test_concurrent_duplicate_submit_waits_for_stored_response(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        h = self._worker_headers(attempt)
        started = threading.Event()
        results: dict[str, object] = {}

        def first_uncommitted() -> None:
            async def run() -> None:
                async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                    async with conn.transaction():
                        await worker_submit.submit_result(
                            conn,
                            org_id=ORG.organization.id,
                            attempt_id=attempt["attempt_id"],
                            worker_id="worker-test-1",
                            fencing_token=attempt["fencing_token"],
                            result=body,
                        )
                        started.set()
                        await asyncio.sleep(1.5)

            asyncio.run(run())

        def second_http() -> None:
            assert started.wait(timeout=15)
            results["response"] = self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/submit",
                headers=h,
                json=body,
            )

        t1 = threading.Thread(target=first_uncommitted)
        t2 = threading.Thread(target=second_http)
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)
        r = results.get("response")
        assert r is not None
        self.assertEqual(r.status_code, 200, getattr(r, "text", r))
        self.assertEqual(r.json()["verdict"], "ACCEPTED")

    def test_duplicate_submit_returns_stored_response(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        h = self._worker_headers(attempt)
        r1 = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit", headers=h, json=body
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit", headers=h, json=body
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r1.json(), r2.json())

    def test_duplicate_submit_different_body_is_409(self) -> None:
        self._start_job()
        attempt = self._claim()
        body = _agent_result(attempt)
        h = self._worker_headers(attempt)
        self.assertEqual(
            self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/submit", headers=h, json=body
            ).status_code,
            200,
        )
        body2 = _agent_result(attempt, blocks=[{"kind": "text", "text": "Different reply."}])
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit", headers=h, json=body2
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "conflict")

    def test_submit_output_not_from_this_attempt_is_422(self) -> None:
        inst = self._start_job()
        a1 = self._claim()
        brief = self._save_brief(a1)
        self.assertEqual(brief.status_code, 201, brief.text)
        art = brief.json()
        self.client.post(
            f"/api/worker/attempts/{a1['attempt_id']}/submit",
            headers=self._worker_headers(a1),
            json=_agent_result(a1),
        )
        turn = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "Again", "client_turn_id": "second-turn"},
        )
        self.assertEqual(turn.status_code, 202, turn.text)
        a2 = self._claim()
        body = _agent_result(a2)
        body["output_artifact_refs"] = [
            {
                "artifact_id": art["artifact_id"],
                "version": art["version"],
                "content_hash": art["content_hash"],
            }
        ]
        r = self.client.post(
            f"/api/worker/attempts/{a2['attempt_id']}/submit",
            headers=self._worker_headers(a2),
            json=body,
        )
        self.assertEqual(r.status_code, 422, r.text)

    def test_settlement_uses_accumulated_usage_when_consumed_lower(self) -> None:
        self._start_job()
        attempt = self._claim()
        self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/events",
            headers=self._worker_headers(attempt),
            json={
                "events": [
                    {
                        "event_type": "ModelInvoked",
                        "redacted_summary": "step",
                        "attributes": {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.05},
                    }
                ],
            },
        )
        settled_before = self._ledger_settled()
        body = _agent_result(
            attempt,
            consumed={
                "tokens_in": 1,
                "tokens_out": 1,
                "cost_usd": 0.001,
                "time_s": 0.0,
                "steps": 1,
                "actions": 0,
            },
        )
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/submit",
            headers=self._worker_headers(attempt),
            json=body,
        )
        self.assertEqual(r.status_code, 200, r.text)
        settled_after = self._ledger_settled()
        self.assertGreater(settled_after, settled_before)

    def test_ask_questions_then_post_turn_readmits(self) -> None:
        inst = self._start_job()
        attempt = self._claim()
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/questions",
            headers=self._worker_headers(attempt),
            json={"blocks": [{"kind": "text", "text": "Which site?"}], "questions": ["North or south?"]},
        )
        self.assertEqual(r.status_code, 201, r.text)
        task_state = _pg.admin_sql(
            self.db,
            f"select state from work.tasks where id = '{attempt['task_id']}';",
        ).stdout.strip()
        self.assertEqual(task_state, "WAITING_INPUT")
        turn = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "North site", "client_turn_id": "after-questions"},
        )
        self.assertEqual(turn.status_code, 202, turn.text)
        self.assertIsNotNone(turn.json().get("attempt_id"))
        live = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where task_id = '{attempt['task_id']}'"
            f" and state in ('ADMITTED', 'CLAIMED');",
        ).stdout.strip()
        self.assertEqual(live, "1")

    def test_stream_wrong_turn_id_is_422(self) -> None:
        self._start_job()
        attempt = self._claim()
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/events",
            headers=self._worker_headers(attempt),
            json={"stream": [{"turn_id": "turn_not_this_one", "seq": 1, "text": "nope"}]},
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["code"], "validation_failed")

    def test_delta_published_only_for_turn_author(self) -> None:
        self._start_job()
        attempt = self._claim()
        turn_id = attempt["turn_id"]
        assert turn_id
        with patch("aos.kernel.worker_events.OutboxHub.publish_delta", new_callable=AsyncMock) as pub:
            r = self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/events",
                headers=self._worker_headers(attempt),
                json={"stream": [{"turn_id": turn_id, "seq": 1, "text": "Hi"}]},
            )
            self.assertEqual(r.status_code, 202, r.text)
            pub.assert_awaited_once()
            kwargs = pub.await_args.kwargs
            self.assertEqual(kwargs["recipient_person_id"], "faisal")
            self.assertEqual(kwargs["turn_id"], turn_id)


if __name__ == "__main__":
    unittest.main()
