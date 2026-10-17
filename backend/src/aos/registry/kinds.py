"""The kinds a domain pack may contain.

Every pack file shares one envelope: ``apiVersion: aos/v1``, ``kind``, ``metadata`` and
``spec``. Each model forbids unknown keys, so a domain field (a customer, an order, a price)
can never be smuggled onto a kernel kind: it fails schema validation instead.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "aos/v1"
NAME_RE = r"^[a-z][a-z0-9_]{1,63}$"
Name = Annotated[str, Field(pattern=NAME_RE)]

# The kernel's Work Types. A pack selects from these; it does not invent new ones.
WORK_TYPES = ("analysis", "document_draft", "outbound_communication", "record_update", "reconciliation")
WorkType = Literal["analysis", "document_draft", "outbound_communication", "record_update", "reconciliation"]

# The Workspace's catalogue views (gap 8). Custom views are deferred.
VIEW_TYPES = (
    "document", "sheet", "form", "comparison", "message_composer", "rubric",
    "tracker", "approval_pack", "record_preview", "file_viewer", "dashboard",
)

# Tools every Seat has from the kernel itself; they never leave AOS.
# Kernel tools every Seat has; they map to the worker endpoints in openapi.yaml (tag worker) and never leave AOS.
# Agent-to-agent delegation (request_work) is deferred beyond the POC.
NATIVE_TOOLS = ("read_artifact", "save_draft", "ask_question", "request_action", "checkpoint", "submit")

# Context resolvers the kernel provides. Artifact type names also resolve to their latest version.
BUILTIN_RESOLVERS = ("job_snapshot", "running_summary", "recent_messages", "pending_items")

POLICY_EFFECTS = ("ALLOW", "REQUIRE_APPROVAL", "DENY", "NEVER")
Effect = Literal["ALLOW", "REQUIRE_APPROVAL", "DENY", "NEVER"]

DURATION_RE = re.compile(r"^\d+(s|m|h|d)$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(Strict):
    name: Name
    version: int = Field(ge=1)
    owner: Name


class Envelope(Strict):
    api_version: Literal["aos/v1"] = Field(alias="apiVersion")
    kind: str
    metadata: Metadata


# ---------------------------------------------------------------- Pack

class Observability(Strict):
    stage_targets: dict[Name, str] = {}
    approval_due_default: str = "1d"
    seat_alerts: dict[str, float] = {}
    prompt_capture: bool = False

    @field_validator("approval_due_default")
    @classmethod
    def _duration(cls, v: str) -> str:
        if not DURATION_RE.match(v):
            raise ValueError(f"not a duration like 2d or 15m: {v!r}")
        return v


class PackSpec(Strict):
    kernel: Literal["aos/v1"]
    description: str = ""
    observability: Observability = Observability()


class Pack(Envelope):
    kind: Literal["Pack"]
    spec: PackSpec


# ---------------------------------------------------------------- Role, Resource

class RoleSpec(Strict):
    work_types: list[WorkType] = Field(min_length=1)


class Role(Envelope):
    kind: Literal["Role"]
    spec: RoleSpec


class ResourceSpec(Strict):
    description: str = ""
    actions: list[Name] = Field(min_length=1)
    lives_in: Literal["aos_store", "connector"]
    classification: Literal["shareable", "internal", "restricted"] = "internal"


class Resource(Envelope):
    kind: Literal["Resource"]
    spec: ResourceSpec


# ---------------------------------------------------------------- ArtifactType

class FieldSpec(Strict):
    type: Literal["string", "text", "integer", "number", "money", "date", "datetime", "list", "object", "boolean"]
    required: bool = False
    classification: Literal["shareable", "internal", "restricted"] | None = None
    label: str | None = None  # display label; the UI falls back to the field name, humanized


class ViewSpec(Strict):
    type: str
    columns: list[str] | None = None
    export: Literal["excel", "csv"] | None = None

    @field_validator("type")
    @classmethod
    def _catalogue(cls, v: str) -> str:
        if v not in VIEW_TYPES:
            raise ValueError(f"view type {v!r} is not in the catalogue {VIEW_TYPES}")
        return v


class ArtifactTypeSpec(Strict):
    description: str = ""
    fields: dict[Name, FieldSpec] = Field(min_length=1)
    row_based: bool = False
    classification: Literal["shareable", "internal", "restricted"] = "internal"
    view: ViewSpec
    # participant role -> "all" | "none" | list of visible fields
    visibility: dict[Name, Literal["all", "none"] | list[Name]] = Field(min_length=1)


class ArtifactType(Envelope):
    kind: Literal["ArtifactType"]
    spec: ArtifactTypeSpec


# ---------------------------------------------------------------- Seat, Skill

class RuntimeSpec(Strict):
    adapter: Literal["langgraph_agent", "fake"]
    model_alias: Name


class LimitsSpec(Strict):
    run_minutes: int = Field(gt=0)
    actions_per_run: int = Field(gt=0)
    daily_cost_usd: float = Field(gt=0)
    attempt_cost_usd: float = Field(gt=0)
    attempt_tokens: int = Field(gt=0)
    attempt_steps: int = Field(gt=0, description="Model calls per attempt (TaskContract budget.steps).")
    attempt_actions: int = Field(gt=0, description="Tool and action calls per attempt (TaskContract budget.actions).")


class DelegationSpec(Strict):
    targets: list[Name] = []
    work_types: list[WorkType] = []
    max_depth: int = Field(default=1, ge=0, le=3)


class SeatSpec(Strict):
    display_name: str
    placement: str = Field(pattern=r"^[a-z0-9_]+(/[a-z0-9_]+)*$")
    role: Name
    skills: list[Name] = Field(min_length=1)
    resources: list[Name] = Field(min_length=1)
    authority_profile: str = Field(pattern=r"^[a-z][a-z0-9_]+@\d+$")
    autonomy_mode: Literal["supervised", "assisted", "autonomous"] = "supervised"
    runtime: RuntimeSpec
    limits: LimitsSpec
    delegation: DelegationSpec | None = None
    evals: list[Name] = []


class Seat(Envelope):
    kind: Literal["Seat"]
    spec: SeatSpec


class SkillSpec(Strict):
    work_types: list[WorkType] = Field(min_length=1)
    instructions: str
    reads: list[Name] = []
    produces: list[Name] = []
    may_request: list[Name] = []
    verifiers: list[Name] = []


class Skill(Envelope):
    kind: Literal["Skill"]
    spec: SkillSpec


# ---------------------------------------------------------------- Verifier, ToolProvider

class VerifierSpec(Strict):
    description: str = ""
    method: Literal["rule", "model"]
    applies_to: list[Name] = Field(min_length=1)
    implementation: str = Field(pattern=r"^[a-z_][a-z0-9_.]+$")


class Verifier(Envelope):
    kind: Literal["Verifier"]
    spec: VerifierSpec


class ToolSpec(Strict):
    resource: Name
    action: Name
    tool_class: Literal["read", "compute", "staged_write", "committed_effect"] = Field(alias="class")
    reconcile_with: Name | None = None
    implementation: str | None = None
    input_schema: dict[str, Any] | None = None


class Governance(Strict):
    require_policy_evaluation: bool = True
    allow_direct_runtime_credentials: Literal[False] = False


class InboundSpec(Strict):
    event: str
    auth: Literal["hmac", "oauth"]


class ToolProviderSpec(Strict):
    description: str = ""
    transport: Literal["mcp", "builtin"]
    endpoint: str | None = None
    inbound: InboundSpec | None = None
    tools: dict[Name, ToolSpec] = Field(min_length=1)
    governance: Governance = Governance()

    @model_validator(mode="after")
    def _endpoint(self) -> "ToolProviderSpec":
        if self.transport == "mcp" and not self.endpoint:
            raise ValueError("an mcp tool provider needs an endpoint")
        for name, tool in self.tools.items():
            if tool.tool_class == "committed_effect" and not tool.reconcile_with:
                raise ValueError(f"committed-effect tool {name!r} needs reconcile_with (unknown outcomes)")
        return self


class ToolProvider(Envelope):
    kind: Literal["ToolProvider"]
    spec: ToolProviderSpec


# ---------------------------------------------------------------- Policy

class Grant(Strict):
    resource: Name
    actions: list[Name] = Field(min_length=1)
    effect: Effect


class ApprovalStep(Strict):
    approver: str = Field(pattern=r"^participant:[a-z][a-z0-9_]+$")
    kind: Literal["content", "release"] = "release"
    when: str | None = None


class ApprovalSpec(Strict):
    chain: list[ApprovalStep] = Field(min_length=1)
    segregation: list[Literal["not_requester", "distinct_approvers", "not_configurer"]] = []
    due: str = "1d"


class Rule(Strict):
    id: Name
    action: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    effect: Effect
    approval: ApprovalSpec | None = None
    conditions: list[str] = []
    subjects: list[str] = []

    @model_validator(mode="after")
    def _approval(self) -> "Rule":
        if self.effect == "REQUIRE_APPROVAL" and self.approval is None:
            raise ValueError(f"rule {self.id}: REQUIRE_APPROVAL needs an approval chain")
        if self.effect != "REQUIRE_APPROVAL" and self.approval is not None:
            raise ValueError(f"rule {self.id}: only REQUIRE_APPROVAL rules take an approval chain")
        return self


class PolicySpec(Strict):
    type: Literal["authority_profile", "gate_rules"]
    workflow: Name | None = None
    grants: list[Grant] = []
    rules: list[Rule] = []

    @model_validator(mode="after")
    def _shape(self) -> "PolicySpec":
        if self.type == "authority_profile" and (not self.grants or self.rules):
            raise ValueError("an authority_profile holds grants only")
        if self.type == "gate_rules" and (not self.rules or self.grants):
            raise ValueError("gate_rules hold rules only")
        return self


class Policy(Envelope):
    kind: Literal["Policy"]
    spec: PolicySpec


# ---------------------------------------------------------------- WorkflowDefinition

class TaskTemplate(Strict):
    template: Name
    skill: Name
    work_type: WorkType
    verifier: Name | None = None


class StateSpec(Strict):
    label: str
    view: Name | None = None
    final: bool = False
    tasks: list[TaskTemplate] = []
    on_event: dict[str, TaskTemplate] = {}


class Participant(Strict):
    bind: Literal["at_creation", "by_claim", "by_rule", "by_decision"]
    queue: str | None = None
    rule: str | None = None
    org_roles: list[Name] = Field(default_factory=list)


class ParallelRegion(Strict):
    on: str
    region: Name
    start: TaskTemplate
    join_at: Name
    join_guard: str | None = None


class Transition(Strict):
    from_: Name = Field(alias="from")
    to: Name
    on: str | list[str]
    by: Name | None = None
    guard: str | None = None
    effects: list[dict[str, Any]] = []

    @property
    def events(self) -> list[str]:
        return [self.on] if isinstance(self.on, str) else list(self.on)


class Timer(Strict):
    after: str
    demo_after: str | None = None
    emits: Name

    @field_validator("after", "demo_after")
    @classmethod
    def _duration(cls, v: str | None) -> str | None:
        if v is not None and not DURATION_RE.match(v):
            raise ValueError(f"not a duration like 5d or 15m: {v!r}")
        return v


AttributeType = Literal["int", "decimal", "string", "bool", "date"]


class WorkflowAttributeSpec(Strict):
    """Workflow instance attribute: type plus classification (short YAML form defaults to internal)."""

    type: AttributeType
    classification: Literal["shareable", "internal", "restricted"] = "internal"


class WorkflowSpec(Strict):
    title: str
    description: str = ""
    id_prefix: str = Field(default="JOB", pattern=r"^[A-Z]{2,5}$")  # job numbers: <prefix>-0001
    start_on: str
    start_roles: list[Name] = Field(min_length=1)
    seat_role: Name
    initial: Name
    participants: dict[Name, Participant] = Field(min_length=1)
    attributes: dict[Name, WorkflowAttributeSpec] = {}

    @field_validator("attributes", mode="before")
    @classmethod
    def _normalize_attributes(cls, v: object) -> object:
        if not isinstance(v, dict):
            return v
        out: dict[str, object] = {}
        for key, val in v.items():
            if isinstance(val, str):
                out[key] = {"type": val, "classification": "internal"}
            else:
                out[key] = val
        return out
    events: list[Name] = []
    states: dict[Name, StateSpec] = Field(min_length=2)
    parallel: list[ParallelRegion] = []
    transitions: list[Transition] = Field(min_length=1)
    timers: dict[Name, Timer] = {}


class WorkflowDefinition(Envelope):
    kind: Literal["WorkflowDefinition"]
    spec: WorkflowSpec


# ---------------------------------------------------------------- EvalSuite

class EvalSuiteSpec(Strict):
    description: str = ""
    targets: list[Name] = Field(min_length=1)
    workflow: Name
    at_state: Name | None = None
    as_participant: Name | None = None
    cases: list[str] = []
    script: str | None = None
    expect: dict[str, Any]
    pass_condition: dict[str, float]

    @model_validator(mode="after")
    def _cases_or_script(self) -> "EvalSuiteSpec":
        if not self.cases and not self.script:
            raise ValueError("an eval suite needs cases or a script")
        return self


class EvalSuite(Envelope):
    kind: Literal["EvalSuite"]
    spec: EvalSuiteSpec


KINDS: dict[str, type[Envelope]] = {
    "Pack": Pack,
    "Role": Role,
    "Resource": Resource,
    "ArtifactType": ArtifactType,
    "Seat": Seat,
    "Skill": Skill,
    "Verifier": Verifier,
    "ToolProvider": ToolProvider,
    "Policy": Policy,
    "WorkflowDefinition": WorkflowDefinition,
    "EvalSuite": EvalSuite,
}
