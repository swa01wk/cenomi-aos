"""Worker token must not appear in logs or config repr."""

from __future__ import annotations

import asyncio
import logging
import unittest

from aos.worker.config import WorkerConfig
from aos.worker.errors import AuthFailed
from aos.worker.default_fake import assist_complete
from aos.worker.runner import Worker
from aos.worker.runtime import ScriptedRuntime

from . import _pg
from .worker_harness import WorkerHarness, make_http_client


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerTokenRedactionTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def test_token_not_in_logs_or_repr(self) -> None:
        await asyncio.to_thread(self._start_job)
        token = self.worker_auth()["Authorization"].split(" ", 1)[1]
        client = await make_http_client(self)
        worker = Worker("worker-test-1", client, ScriptedRuntime([assist_complete]), ("assist",))

        root = logging.getLogger()
        prior_root = root.level
        prior_httpx = logging.getLogger("httpx").level
        prior_httpcore = logging.getLogger("httpcore").level
        root.setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("httpcore").setLevel(logging.DEBUG)
        records: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda rec: records.append(rec.getMessage())  # type: ignore[method-assign]
        handler.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            await asyncio.wait_for(worker.run_once(), 30)
            client._token = "bad-token-for-401"
            with self.assertRaises(AuthFailed):
                await asyncio.wait_for(worker.run_once(), 30)
        finally:
            root.removeHandler(handler)
            root.setLevel(prior_root)
            logging.getLogger("httpx").setLevel(prior_httpx)
            logging.getLogger("httpcore").setLevel(prior_httpcore)

        cfg = WorkerConfig(
            api_url="http://test/api",
            worker_token=token,
            worker_id="worker-test-1",
            lanes=("assist",),
            runtime="fake",
            checkpoint_database_url="postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos",
            poll_min_s=1.0,
            poll_max_s=5.0,
            submit_shutdown_timeout_s=30.0,
        )
        blob = "".join(records) + repr(cfg)
        self.assertNotIn(token, blob)
        self.assertIn("<redacted>", repr(cfg))
        await client.aclose()
