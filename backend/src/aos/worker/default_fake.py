"""Default FakeRuntime steps for AOS_RUNTIME=fake in development."""

from __future__ import annotations

from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt


def minimal_agent_result(attempt: WorkerAttempt, *, text: str = "OK") -> AgentResult:
    contract = attempt["contract"]
    return {
        "schema_version": "aos.agent_result/1",
        "contract_id": contract["contract_id"],
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "output_artifact_refs": [],
        "evidence_refs": [],
        "input_versions": dict(contract.get("dependency_versions") or {}),
        "consumed_budget": {
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "time_s": 0.0,
            "steps": 1,
            "actions": 0,
        },
        "summary": "Completed with the fake runtime.",
        "reply_blocks": [{"kind": "text", "text": text}],
    }


async def assist_complete(attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
    await ctx.post_events(
        events=[{"event_type": "AgentStarted", "redacted_summary": "fake runtime started"}]
    )
    await ctx.get_contract()
    await ctx.assemble_context(reason="start")
    return minimal_agent_result(attempt)
