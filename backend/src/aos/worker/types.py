"""Worker-side API shapes (TypedDict); not generated from OpenAPI."""

from typing import Any, NotRequired, TypedDict


class WorkerAttempt(TypedDict):
    attempt_id: str
    task_id: str
    instance_id: str
    n: int
    fencing_token: int
    lease_seconds: int
    kind: str
    contract: dict[str, Any]
    resume: NotRequired[dict[str, Any] | None]  # checkpoint_id, thread_id (LangGraph thread to continue)
    turn_id: NotRequired[str | None]


class ConsumedBudget(TypedDict):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    time_s: float
    steps: int
    actions: int


class AgentResult(TypedDict):
    schema_version: str
    contract_id: str
    attempt_id: str
    status: str
    output_artifact_refs: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]
    input_versions: dict[str, int]
    consumed_budget: ConsumedBudget
    summary: str
    reply_blocks: NotRequired[list[dict[str, Any]]]
    failure_category: NotRequired[str]


class SubmitResponse(TypedDict, total=False):
    verdict: str
    task_state: str
    verifier: dict[str, Any] | None
    next_attempt: bool
