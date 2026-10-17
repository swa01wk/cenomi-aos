"""Worker process must not import kernel or api; psycopg only via checkpointer.py."""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO / "backend" / "src" / "aos" / "worker"
CHECKPOINTER_MODULE = "checkpointer.py"

_FORBIDDEN_IMPORT_ROOTS = frozenset({"psycopg", "langgraph.checkpoint.postgres"})


def _import_root(name: str) -> str | None:
    if name == "psycopg" or name.startswith("psycopg."):
        return "psycopg"
    if name == "langgraph.checkpoint.postgres" or name.startswith("langgraph.checkpoint.postgres."):
        return "langgraph.checkpoint.postgres"
    return None


def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root:
                    found.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = _import_root(node.module)
                if root:
                    found.add(root)
    return found


class WorkerImportBoundaryTests(unittest.TestCase):
    def test_only_checkpointer_imports_psycopg_or_langgraph_postgres(self) -> None:
        offenders: list[str] = []
        for path in sorted(WORKER_SRC.glob("*.py")):
            if path.name == CHECKPOINTER_MODULE:
                continue
            bad = _collect_imports(path) & _FORBIDDEN_IMPORT_ROOTS
            if bad:
                offenders.append(f"{path.relative_to(REPO)}: {', '.join(sorted(bad))}")
        self.assertEqual(offenders, [], "forbidden imports outside checkpointer.py")

    def test_worker_subprocess_has_no_kernel_or_api_modules(self) -> None:
        # Before M1-AG-04 this also forbade psycopg:
        # bad = {m for m in sys.modules if m.startswith(("aos.kernel", "aos.api", "psycopg"))}
        token_script = """
import os
os.environ.setdefault("AOS_RUNTIME", "fake")
os.environ.setdefault(
    "AOS_CHECKPOINT_DATABASE_URL",
    "postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos"
    "?options=-c%20search_path%3Dlg_checkpoints",
)
os.environ.setdefault("AOS_WORKER_TOKEN", "unused")
"""
        script = (
            token_script
            + """
import sys
import aos.worker.__main__  # noqa: F401
bad = {m for m in sys.modules if m.startswith(("aos.kernel", "aos.api"))}
if bad:
    raise SystemExit("forbidden: " + ", ".join(sorted(bad)))
"""
        )
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = f"{REPO / 'backend' / 'src'}:{REPO / 'backend' / '.vendor'}"
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
