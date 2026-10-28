"""Copies of the demo pack for test fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from aos.registry.loader import parse_yaml

REPO = Path(__file__).resolve().parents[2]
DEMO_PACK = REPO / "packs" / "procurement_demo"


def copy_demo_pack(packs_dir: Path, *, intake_task: bool = True) -> Path:
    """Copy the demo pack into ``packs_dir``.

    ``intake_task=False`` drops the intake state's Task, for suites that test assist turns: with it, the first
    message goes to the intake Task instead of an assist attempt.
    """
    dest = packs_dir / "procurement_demo"
    shutil.copytree(DEMO_PACK, dest)
    if not intake_task:
        wf = dest / "workflows" / "quick_quote.yaml"
        doc = parse_yaml(wf.read_text())
        doc["spec"]["states"]["intake"].pop("tasks", None)
        wf.write_text(yaml.safe_dump(doc, sort_keys=False))
    return dest
