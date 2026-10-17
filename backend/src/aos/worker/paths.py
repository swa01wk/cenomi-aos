"""Worker-only paths (no kernel imports)."""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_REPO_ROOT = _PKG.parents[4]


def schema_dir() -> Path:
    raw = os.environ.get("AOS_CONTRACT_SCHEMAS_DIR")
    if raw:
        path = Path(raw)
    else:
        path = _REPO_ROOT / "docs" / "specs" / "contracts" / "schemas"
    if not path.is_dir():
        raise RuntimeError(f"contract schemas directory missing: {path}")
    task = path / "task-contract.schema.json"
    if not task.is_file():
        raise RuntimeError(f"task-contract.schema.json missing under {path}")
    return path
