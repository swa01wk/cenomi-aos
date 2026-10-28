"""Task graph and the intake Task (M2-AG-01): start, ask, resume on input, submit outputs."""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from typing import Any

from aos.worker.checkpointer import CheckpointerHandle
from aos.worker.http_client import HttpKernelClient
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime

from . import _pg
from .test_worker_api import WorkerHarness
from .worker_harness import make_http_client, mock_erp_hook


class _RecordingKernel:
    def __init__(self, inner: HttpKernelClient) -> None:
        self._inner = inner
        self.results: list[dict[str, Any]] = []
        self.asked: list[list[str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def submit_result(self, attempt, result):  # type: ignore[no-untyped-def]
        self.results.append(dict(result))
        return await self._inner.submit_result(attempt, result)

    async def ask_questions(self, attempt, *, blocks, questions=None):  # type: ignore[no-untyped-def]
        self.asked.append(list(questions or []))
        return await self._inner.ask_questions(attempt, blocks=blocks, questions=questions)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class IntakeTaskTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    INTAKE_TASK = True

    def sql(self, query: str) -> str:
        return _pg.admin_sql(self.db, query).stdout.strip()

    def tasks(self, inst: str) -> dict[str, tuple[str, int, int]]:
        rows = self.sql(
            f"select template, state, attempts_used, max_attempts from work.tasks where instance_id = '{inst}';"
        )
        out = {}
        for line in rows.splitlines():
            template, state, used, mx = line.split("|")
            out[template] = (state, int(used), int(mx))
        return out

    def post_turn(self, inst: str, text: str, person: str = "faisal") -> dict:
        r = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth(person), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": text, "client_turn_id": str(uuid.uuid4())},
        )
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    async def run_worker(self, rec: _RecordingKernel) -> str:
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            worker = Worker("worker-test-1", rec, FakeRuntime(checkpointer=handle), ("assist", "task"))
            return await asyncio.wait_for(worker.run_once(), 120)
        finally:
            await handle.close()

    async def recording_client(self) -> _RecordingKernel:
        rec = _RecordingKernel(await make_http_client(self, invoke_hook=mock_erp_hook))
        self.addAsyncCleanup(rec._inner.aclose)
        return rec

    async def test_start_hands_the_first_turn_to_the_intake_task(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        tasks = self.tasks(inst)
        self.assertEqual(tasks["assist"][:2], ("CREATED", 0))
        self.assertEqual(tasks["request_intake"], ("RUNNING", 1, 4))
        first_turn = self.sql(f"select id from work.turns where instance_id = '{inst}' order by seq limit 1;")

        rec = await self.recording_client()
        self.assertIsNone(await rec.claim("worker-test-1", ["assist"]))
        attempt = await rec.claim("worker-test-1", ["task"])
        assert attempt is not None
        self.assertEqual(attempt["contract"]["kind"], "task")
        self.assertEqual(attempt["contract"]["template"], "request_intake")
        self.assertEqual(attempt["contract"]["permission_scope"]["classification_ceiling"], "internal")
        self.assertEqual(attempt["turn_id"], first_turn)

    async def test_intake_task_asks_resumes_on_the_answer_and_submits_the_brief(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        rec = await self.recording_client()

        self.assertEqual(await self.run_worker(rec), "waiting")
        self.assertEqual(len(rec.asked), 1)
        self.assertEqual(self.tasks(inst)["request_intake"][0], "WAITING_INPUT")
        self.assertEqual(rec.results, [])

        body = await asyncio.to_thread(self.post_turn, inst, "North warehouse by 1 November, budget 15000")
        self.assertIsNotNone(body["attempt_id"])
        task_of_attempt = self.sql(
            f"select t.template from work.attempts a join work.tasks t on t.id = a.task_id"
            f" where a.id = '{body['attempt_id']}';"
        )
        self.assertEqual(task_of_attempt, "request_intake")
        state, used, mx = self.tasks(inst)["request_intake"]
        self.assertEqual((state, used), ("RUNNING", 2))
        self.assertEqual(mx, used - 1 + 4, "each answer brings a fresh set of retries")
        self.assertEqual(self.tasks(inst)["assist"][1], 0, "the assist Task never ran")

        self.assertEqual(await self.run_worker(rec), "submitted")
        self.assertEqual(len(rec.results), 1)
        result = rec.results[0]
        self.assertNotIn("reply_blocks", result)
        self.assertEqual(result["summary"], "Thanks, your brief is updated.")
        brief = self.sql(
            "select v.artifact_id, v.version, v.content_hash from work.artifact_versions v"
            " join work.artifacts a on a.id = v.artifact_id"
            f" where a.instance_id = '{inst}' and a.artifact_type = 'brief' order by v.version desc limit 1;"
        ).split("|")
        self.assertEqual(
            result["output_artifact_refs"],
            [{"artifact_id": brief[0], "version": 2, "content_hash": brief[2]}],
        )
        self.assertEqual(self.tasks(inst)["request_intake"][0], "COMPLETED", "brief_schema passed")
        self.assertEqual(
            self.sql(f"select verification->>'verdict' from work.artifact_versions where artifact_id = '{brief[0]}'"
                     " and version = 2;"),
            "PASS",
        )
        decision = self.sql(
            f"select for_role from work.pending_items where instance_id = '{inst}' and status = 'open'"
            " and kind = 'decision';"
        )
        self.assertEqual(decision, "requester", "the requester is asked to confirm the brief")
        self.assertEqual(
            self.sql(f"select data->>'verdict' from evidence.outbox where instance_id = '{inst}'"
                     " and event_type = 'verification.completed';"),
            "PASS",
        )

    async def test_turn_while_the_task_runs_is_held_for_it(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        body = await asyncio.to_thread(self.post_turn, inst, "Also, they must fold flat.")
        self.assertIsNone(body["attempt_id"])
        tasks = self.tasks(inst)
        self.assertEqual(tasks["assist"][1], 0)
        self.assertEqual(tasks["request_intake"][1], 1)

    async def test_turn_after_the_task_finished_goes_to_assist(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        self.sql(
            "update work.attempts set state = 'ENDED', outcome = 'submitted', ended_at = now() where task_id in"
            f" (select id from work.tasks where instance_id = '{inst}' and template = 'request_intake');"
            f" update work.tasks set state = 'COMPLETED' where instance_id = '{inst}' and template = 'request_intake';"
        )
        body = await asyncio.to_thread(self.post_turn, inst, "Where are we?")
        self.assertIsNotNone(body["attempt_id"])
        kind = self.sql(
            f"select t.kind from work.attempts a join work.tasks t on t.id = a.task_id where a.id = '{body['attempt_id']}';"
        )
        self.assertEqual(kind, "assist")


if __name__ == "__main__":
    unittest.main()
