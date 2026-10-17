"""Helpers for async HTTP worker tests."""

from __future__ import annotations

import httpx
from httpx import ASGITransport
from mcp.client.client import Client

from aos.api import create_app
from aos.connectors import mock_erp
from aos.connectors.base import ConnectorConfig
from aos.gateway.broker import CredentialBroker
from aos.kernel.auth import issue_worker_token
from aos.kernel.settings import Settings
from aos.worker.default_fake import minimal_agent_result
from aos.worker.http_client import HttpKernelClient

from . import _pg
from .test_worker_api import ORG, WorkerHarness

__all__ = [
    "WorkerHarness",
    "minimal_agent_result",
    "make_http_client",
    "settings_with_lease",
    "mock_erp_hook",
    "MOCK_ERP_SECRETS",
]

MOCK_ERP_SECRETS = {"mock_erp": "erp-test-secret", "mock_mail": "mail-test-secret"}
_ERP_SERVER, _ = mock_erp.build_server(
    ConnectorConfig(name="mock_erp", secret=MOCK_ERP_SECRETS["mock_erp"])
)


async def mock_erp_hook(*, connector: str, tool: str, arguments: dict):
    async with Client(_ERP_SERVER) as c:
        return await c.call_tool(tool, arguments)


def settings_with_lease(harness: WorkerHarness, lease_seconds: float) -> Settings:
    gateway = min(harness.settings.gateway_timeout_seconds, lease_seconds / 2)
    if gateway >= lease_seconds:
        gateway = max(0.05, lease_seconds - 0.01)
    return Settings.from_env(
        database_url=_pg.kernel_url(harness.db),
        packs_dir=harness.packs,
        session_secret=harness.settings.session_secret,
        scheduler_interval_seconds=60.0,
        worker_lease_seconds=lease_seconds,
        gateway_timeout_seconds=gateway,
        connector_secrets=harness.settings.connector_secrets,
        connector_urls=harness.settings.connector_urls,
    )


async def make_http_client(
    harness: WorkerHarness,
    worker_id: str = "worker-test-1",
    *,
    settings: Settings | None = None,
    invoke_hook=None,
) -> HttpKernelClient:
    app = create_app(settings or harness.settings)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    harness.addAsyncCleanup(lifespan.__aexit__, None, None, None)
    if invoke_hook is not None:
        app.state.kernel.gateway._invoke_hook = invoke_hook
        app.state.kernel.broker = CredentialBroker(harness.settings.connector_secrets)
    token = issue_worker_token(ORG.organization.id, worker_id, harness.settings.session_secret)
    raw = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api")
    return HttpKernelClient("http://test/api", token, client=raw)
