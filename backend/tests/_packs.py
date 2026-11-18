"""Copies of the demo pack for test fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from aos.registry.loader import parse_yaml

REPO = Path(__file__).resolve().parents[2]
DEMO_PACK = REPO / "packs" / "procurement_demo"


def copy_demo_pack(
    packs_dir: Path,
    *,
    intake_task: bool = True,
    initial: str | None = None,
    assist_skill: str | None = None,
) -> Path:
    """Copy the demo pack into ``packs_dir``.

    ``intake_task=False`` drops the intake state's Task, for suites that test assist turns: with it, the first
    message goes to the intake Task instead of an assist attempt.

    Quick Quote now opens in ``conversation`` and moves to intake once the thread has request detail.
    ``initial="intake"`` starts jobs in intake, for suites about the intake Task itself. ``assist_skill`` swaps the
    assist skill of the opening states, for worker-protocol suites that need an assist turn able to save a brief
    (``sourcing_assist`` produces no artifacts).
    """
    dest = packs_dir / "procurement_demo"
    shutil.copytree(DEMO_PACK, dest)
    if intake_task and initial is None and assist_skill is None:
        return dest
    wf = dest / "workflows" / "quick_quote.yaml"
    doc = parse_yaml(wf.read_text())
    states = doc["spec"]["states"]
    if not intake_task:
        states["intake"].pop("tasks", None)
    if initial is not None and initial != doc["spec"]["initial"]:
        # Drop the old opening state (and its way out) so the new initial leaves nothing unreachable.
        old = doc["spec"]["initial"]
        doc["spec"]["initial"] = initial
        states.pop(old, None)
        doc["spec"]["transitions"] = [t for t in doc["spec"]["transitions"] if t.get("from") != old]
    if assist_skill is not None:
        for name in ("conversation", "intake"):
            states[name]["assist"] = assist_skill
    wf.write_text(yaml.safe_dump(doc, sort_keys=False))
    return dest
