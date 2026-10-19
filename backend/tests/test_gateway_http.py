"""The gateway's real HTTP path against a running mock ERP (other tests use an in-memory MCP client)."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aos.gateway.broker import CredentialBroker, Grant
from aos.gateway.gateway import InvokeSuccess, ToolGateway

SECRET = "gateway-http-test-secret-0123456789abcdef"
SRC = Path(__file__).resolve().parents[1] / "src"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class GatewayHttpTests(unittest.TestCase):
    proc: subprocess.Popen | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        env = {**os.environ, "MOCK_ERP_SECRET": SECRET}
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "aos.connectors.mock_erp", "--host", "127.0.0.1", "--port", str(cls.port),
             "--db", str(Path(cls.tmp.name) / "erp.sqlite")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("mock ERP did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc:
            cls.proc.terminate()
            cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    def test_browse_categories_over_streamable_http(self) -> None:
        broker = CredentialBroker({"mock_erp": SECRET})
        token = broker.mint(
            Grant("mock_erp", "erp_supplier", "read", "act_http", "org_demo", "browse_categories", "att_http")
        )
        gateway = ToolGateway(connector_urls={"mock_erp": f"http://127.0.0.1:{self.port}/mcp"})
        result = asyncio.run(
            gateway.invoke_read(connector="mock_erp", tool="browse_categories", args={"query": ""}, token=token)
        )
        self.assertIsInstance(result, InvokeSuccess, result)
        names = {c["name"] for c in result.content["items"]}  # type: ignore[union-attr]
        self.assertIn("Janitorial equipment", names)


if __name__ == "__main__":
    unittest.main()
