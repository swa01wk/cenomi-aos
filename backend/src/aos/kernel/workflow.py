"""Pure workflow interpreter: event matching, guards, entry tasks (M2).

Persistence, effects execution and parallel joins are wired in later stories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from aos.registry.expressions import ExpressionScope, evaluate
from aos.registry.kinds import TaskTemplate, Transition, WorkflowDefinition

TransitionReason = Literal["no_match", "wrong_role", "guard_failed"]


@dataclass(frozen=True)
class TransitionMatch:
    transition: Transition | None
    reason: TransitionReason | None
    effects: list[dict[str, Any]]
    entry_tasks: list[TaskTemplate]


def _build_scope(
    *,
    attributes: dict[str, Any],
    workflow_ctx: dict[str, Any],
    artifact_ctx: dict[str, Any] | None,
    subject_ctx: dict[str, Any] | None,
) -> ExpressionScope:
    scope: dict[str, dict[str, Any]] = {
        "attr": dict(attributes),
        "workflow": dict(workflow_ctx),
    }
    if artifact_ctx is not None:
        scope["artifact"] = dict(artifact_ctx)
    if subject_ctx is not None:
        scope["subject"] = dict(subject_ctx)
    return scope


def match_transition(
    definition: WorkflowDefinition,
    *,
    state: str,
    event: str,
    actor_role: str | None,
    attributes: dict[str, Any] | None = None,
    workflow_ctx: dict[str, Any] | None = None,
    artifact_ctx: dict[str, Any] | None = None,
    subject_ctx: dict[str, Any] | None = None,
) -> TransitionMatch:
    """Return the first transition that matches *state* and *event*, or why none fired."""
    spec = definition.spec
    attrs = attributes or {}
    wf_ctx = workflow_ctx or {"state": state}
    scope = _build_scope(
        attributes=attrs,
        workflow_ctx=wf_ctx,
        artifact_ctx=artifact_ctx,
        subject_ctx=subject_ctx,
    )

    candidates: list[Transition] = []
    for tr in spec.transitions:
        if tr.from_ != state:
            continue
        if event not in tr.events:
            continue
        candidates.append(tr)

    if not candidates:
        return TransitionMatch(None, "no_match", [], [])

    role_blocked = False
    guard_blocked = False

    for tr in candidates:
        if tr.by is not None:
            if actor_role != tr.by:
                role_blocked = True
                continue
        if tr.guard is not None and not evaluate(tr.guard, scope):
            guard_blocked = True
            continue
        target = spec.states[tr.to]
        return TransitionMatch(tr, None, list(tr.effects), list(target.tasks))

    if guard_blocked:
        return TransitionMatch(None, "guard_failed", [], [])
    if role_blocked:
        return TransitionMatch(None, "wrong_role", [], [])
    return TransitionMatch(None, "no_match", [], [])
