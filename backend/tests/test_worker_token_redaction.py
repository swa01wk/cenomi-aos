"""Worker token must not appear in logs or config repr."""

from __future__ import annotations

import logging
import unittest

from aos.worker.config import WorkerConfig
from aos.worker.default_fake import assist_complete
from aos.worker.http_client import HttpKernelClient
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime

from . import _pg
from .worker_harness import WorkerHarness, make_http_client


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerTokenRedactionTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.setUp()

    async def test_token_not_in_logs_or_repr(self) -> None:
        self._start_job()
        token = self.worker_auth()["Authorization"].split(" ", 1)[1]
        client = make_http_client(self)
        worker = Worker("worker-test-1", client, FakeRuntime([assist_complete]), ("assist",))

        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("httpcore").setLevel(logging.DEBUG)
        with self.assertLogs("aos.worker", level="DEBUG") as cap:
            await worker.run_once()

        cfg = WorkerConfig(
            api_url="http://test/api",
            worker_token=token,
            worker_id="worker-test-1",
            lanes=("assist",),
            runtime="fake",
            poll_min_s=1.0,
            poll_max_s=5.0,
            submit_shutdown_timeout_s=30.0,
        )
        blob = "".join(cap.output) + repr(cfg)
        self.assertNotIn(token, blob)
        self.assertIn("<redacted>", repr(cfg))
        await client.aclose()
