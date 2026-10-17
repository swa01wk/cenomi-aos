"""Helpers for async HTTP worker tests."""

from __future__ import annotations

import httpx
from httpx import ASGITransport

from aos.api import create_app
from aos.kernel.auth import issue_worker_token
from aos.kernel.settings import Settings
from aos.worker.default_fake import minimal_agent_result
from aos.worker.http_client import HttpKernelClient

from . import _pg
from .test_worker_api import ORG, WorkerHarness

__all__ = ["WorkerHarness", "minimal_agent_result", "make_http_client", "settings_with_lease"]


def settings_with_lease(harness: WorkerHarness, lease_seconds: float) -> Settings:
    return Settings.from_env(
        database_url=_pg.kernel_url(harness.db),
        packs_dir=harness.packs,
        session_secret=harness.settings.session_secret,
        scheduler_interval_seconds=60.0,
        worker_lease_seconds=lease_seconds,
        connector_secrets=harness.settings.connector_secrets,
        connector_urls=harness.settings.connector_urls,
    )


def make_http_client(
    harness: WorkerHarness,
    worker_id: str = "worker-test-1",
    *,
    settings: Settings | None = None,
) -> HttpKernelClient:
    app = create_app(settings or harness.settings)
    token = issue_worker_token(ORG.organization.id, worker_id, harness.settings.session_secret)
    raw = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api")
    return HttpKernelClient("http://test/api", token, client=raw)
