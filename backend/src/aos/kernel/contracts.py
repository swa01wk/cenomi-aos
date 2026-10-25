"""Build and freeze TaskContract JSON from pinned pack definitions (M1)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..registry.kinds import EFFECT_COMMIT_WORK_TYPES, NATIVE_TOOLS, BudgetSpec, Participant
from ..registry.loader import load_pack
from . import clock, ids
from .org import OrgModel
from .participants import eval_participant_rule


class PackMaterialError(Exception):
    """Pinned pack on disk does not match the stored version (digest or skill files)."""

    def __init__(self, code: str, status: int, title: str, detail: str) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(title)

_KERNEL_TOOL_NAMES = frozenset({"read_artifact", "save_draft", "ask_question", "request_action", "checkpoint", "submit"})


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def contract_hash(contract: dict[str, Any]) -> str:
    body = {k: v for k, v in contract.items() if k != "contract_hash"}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def verify_pinned_pack_on_disk(
    packs_dir: Path, pack_name: str, pack_version: int, expected_digest: str
) -> None:
    """Same digest check as pack sync: on-disk tree must match the pinned pack_versions row."""
    root = packs_dir / pack_name
    if not root.is_dir():
        raise PackMaterialError(
            "conflict",
            409,
            "Pack folder is missing",
            f"The pack folder {pack_name!r} is not available on this server.",
        )
    loaded = load_pack(root)
    if loaded.manifest is None:
        raise PackMaterialError(
            "conflict",
            409,
            "Pack folder is invalid",
            f"The pack folder {pack_name!r} has no manifest.",
        )
    meta = loaded.manifest.metadata
    if int(meta.version) != int(pack_version):
        raise PackMaterialError(
            "conflict",
            409,
            "Pack version mismatch",
            f"On-disk pack is v{meta.version}; this job is pinned to v{pack_version}.",
        )
    if loaded.digest != expected_digest:
        raise PackMaterialError(
            "conflict",
            409,
            "Pack content changed",
            "The pack on disk no longer matches the published version pinned to this seat.",
        )


def load_skill_instructions(packs_dir: Path, contract: dict[str, Any]) -> str:
    pack = contract.get("pack") or {}
    pack_name = pack.get("name")
    skill = (contract.get("skill") or {}).get("name")
    if not pack_name or not skill:
        raise PackMaterialError(
            "internal",
            500,
            "Contract is incomplete",
            "Missing pack or skill on the frozen contract.",
        )
    root = packs_dir / str(pack_name) / "skills" / str(skill)
    rel = "instructions.md"
    path = root / rel
    if not path.is_file():
        raise PackMaterialError(
            "conflict",
            409,
            "Skill instructions missing",
            f"Instructions file for skill {skill!r} is not on disk.",
        )
    return path.read_text(encoding="utf-8")


def _instructions_sha256(packs_dir: Path, pack_name: str, skill_doc: dict) -> str:
    rel = (skill_doc.get("spec") or {}).get("instructions") or "instructions.md"
    skill_name = skill_doc.get("metadata", {}).get("name", "")
    path = packs_dir / pack_name / "skills" / skill_name / rel
    if not path.is_file():
        raise PackMaterialError(
            "conflict",
            409,
            "Skill instructions missing",
            f"Instructions file {rel!r} for skill {skill_name!r} is not on disk.",
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seat_budget_block(seat_limits: dict[str, Any]) -> dict[str, Any]:
    return {
        "tokens": int(seat_limits["attempt_tokens"]),
        "cost_usd": float(seat_limits["attempt_cost_usd"]),
        "time_s": int(seat_limits["run_minutes"]) * 60,
        "steps": int(seat_limits["attempt_steps"]),
        "actions": int(seat_limits["attempt_actions"]),
        "retries": 2,
        "children": 0,
    }


def _budget_dict(raw: dict[str, Any] | BudgetSpec) -> dict[str, Any]:
    if isinstance(raw, BudgetSpec):
        return raw.model_dump()
    return dict(raw)


def contract_budget_block(
    skill_budget: dict[str, Any] | BudgetSpec,
    seat_limits: dict[str, Any],
    *,
    template_override: dict[str, Any] | BudgetSpec | None = None,
) -> dict[str, Any]:
    """Skill or template budget, each field capped by the Seat limits."""
    source = _budget_dict(template_override if template_override is not None else skill_budget)
    seat = seat_budget_block(seat_limits)
    return {
        "tokens": min(int(source["tokens"]), int(seat["tokens"])),
        "cost_usd": min(float(source["cost_usd"]), float(seat["cost_usd"])),
        "time_s": min(int(source["seconds"]), int(seat["time_s"])),
        "steps": min(int(source["steps"]), int(seat["steps"])),
        "actions": min(int(source["actions"]), int(seat["actions"])),
        "retries": int(source["retries"]),
        "children": 0,
    }


def max_attempts_from_budget(budget: dict[str, Any]) -> int:
    return int(budget["retries"]) + 1


def _tool_index(defs: dict[str, dict[str, dict]]) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for prov_name, prov in defs.get("ToolProvider", {}).items():
        for tname, tool in (prov.get("spec") or {}).get("tools", {}).items():
            out[tname] = (prov_name, tool)
    return out


def _participant_spec(
    defs: dict[str, dict[str, dict]], workflow_name: str, participant_role: str
) -> Participant | None:
    wf = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if not wf:
        return None
    spec = (wf.get("spec") or {}).get("participants") or {}
    raw = spec.get(participant_role)
    if not raw:
        return None
    return Participant.model_validate(raw)


def _candidate_person_ids_for_role(
    org: OrgModel,
    participant: Participant,
) -> list[str]:
    if participant.bind == "at_creation":
        org_roles = set(participant.org_roles or [])
        return [pid for pid, person in org.people.items() if org_roles & set(person.roles)]
    if participant.bind == "by_claim":
        queue = (participant.queue or "").strip()
        if not queue:
            return []
        return [pid for pid, person in org.people.items() if person.team == queue]
    if participant.bind == "by_rule" and participant.rule:
        try:
            return [eval_participant_rule(org, participant.rule)]
        except Exception:
            return []
    return []


def participant_role_classification_ceiling(
    seat_doc: dict,
    defs: dict[str, dict[str, dict]],
    *,
    org: OrgModel | None,
    participant_role: str,
    workflow_name: str,
    person_id: str | None,
) -> str:
    """Clearance for on_behalf_of: bound person, or lowest among candidates when unbound.

    When nobody can be identified (no org, unknown role, no candidates) the answer is the lowest label: a Task
    never gets more than its reader may see because the reader is unknown.
    """
    if person_id and org is not None:
        return participant_classification_ceiling(seat_doc, defs, org=org, person_id=person_id)
    if org is None:
        return "shareable"
    participant = _participant_spec(defs, workflow_name, participant_role)
    if participant is None:
        return "shareable"
    candidates = _candidate_person_ids_for_role(org, participant)
    if not candidates:
        return "shareable"
    ceiling = _seat_classification_ceiling(seat_doc, defs)
    for pid in candidates:
        clearance = participant_classification_ceiling(seat_doc, defs, org=org, person_id=pid)
        ceiling = _min_classification(ceiling, clearance)
    return ceiling


def task_classification_ceiling(
    skill_ceiling: str,
    seat_doc: dict,
    defs: dict[str, dict[str, dict]],
    *,
    org: OrgModel | None,
    workflow_name: str,
    participant_role: str,
    person_id: str | None,
) -> str:
    clearance = participant_role_classification_ceiling(
        seat_doc,
        defs,
        org=org,
        participant_role=participant_role,
        workflow_name=workflow_name,
        person_id=person_id,
    )
    return _min_classification(str(skill_ceiling), clearance)


def _allowed_tools_for_task(
    skill_spec: dict[str, Any],
    work_type: str,
    tools_idx: dict[str, tuple[str, dict]],
) -> list[dict[str, Any]]:
    allowed: list[dict[str, Any]] = [{"name": "read_artifact", "kind": "kernel", "class": "kernel"}]
    if skill_spec.get("produces"):
        allowed.append({"name": "save_draft", "kind": "kernel", "class": "kernel"})
        allowed.append({"name": "ask_question", "kind": "kernel", "class": "kernel"})
    allowed.append({"name": "submit", "kind": "kernel", "class": "kernel"})
    wt = str(work_type)
    for tname in skill_spec.get("may_request") or []:
        if tname in _KERNEL_TOOL_NAMES:
            if tname in ("save_draft", "ask_question", "submit"):
                continue
            allowed.append({"name": tname, "kind": "kernel", "class": "kernel"})
        elif tname in tools_idx:
            prov, tool = tools_idx[tname]
            tool_class = tool.get("class") or tool.get("tool_class") or "read"
            if tool_class == "committed_effect" and wt not in EFFECT_COMMIT_WORK_TYPES:
                continue
            allowed.append(_tool_grant(tname, tool, prov))
    return allowed


def _allowed_tools_for_assist(skill_spec: dict[str, Any], tools_idx: dict[str, tuple[str, dict]]) -> list[dict[str, Any]]:
    allowed: list[dict[str, Any]] = []
    if skill_spec.get("produces"):
        for native in ("save_draft", "ask_question"):
            allowed.append({"name": native, "kind": "kernel", "class": "kernel"})
    for tname in skill_spec.get("may_request") or []:
        if tname in _KERNEL_TOOL_NAMES:
            allowed.append({"name": tname, "kind": "kernel", "class": "kernel"})
        elif tname in tools_idx:
            prov, tool = tools_idx[tname]
            allowed.append(_tool_grant(tname, tool, prov))
    return allowed


def _tool_grant(name: str, tool: dict, provider: str) -> dict[str, Any]:
    tool_class = tool.get("class") or tool.get("tool_class") or "read"
    kind = "compute" if tool_class == "compute" else "connector"
    if name in _KERNEL_TOOL_NAMES:
        kind = "kernel"
        tool_class = "kernel"
    grant: dict[str, Any] = {"name": name, "kind": kind, "class": tool_class}
    if kind == "connector":
        grant["connector"] = provider
        grant["resource"] = tool.get("resource")
        grant["action"] = tool.get("action")
        grant["timeout_s"] = 30
    if tool.get("reconcile_with"):
        grant["reconcile_with"] = tool["reconcile_with"]
    if isinstance(tool.get("input_schema"), dict):
        grant["input_schema"] = tool["input_schema"]
    return grant


def _gate_policy_ref(defs: dict[str, dict[str, dict]], workflow_name: str) -> str:
    for pol in defs.get("Policy", {}).values():
        spec = pol.get("spec") or {}
        if spec.get("type") == "gate_rules" and spec.get("workflow") == workflow_name:
            meta = pol.get("metadata") or {}
            return f"{meta.get('name')}@{meta.get('version')}"
    return "none@0"


def build_assist_contract(
    *,
    packs_dir: Path,
    pack_name: str,
    pack_version: int,
    pack_digest: str,
    defs: dict[str, dict[str, dict]],
    org_id: str,
    instance_id: str,
    task_id: str,
    seat_name: str,
    seat_version: int,
    seat_doc: dict,
    workflow_name: str,
    skill_name: str,
    work_type: str,
    participant_role: str,
    person_id: str,
    attempt_n: int,
    seat_limits: dict[str, Any],
    org: OrgModel | None = None,
) -> dict[str, Any]:
    skill_doc = defs.get("Skill", {}).get(skill_name)
    if skill_doc is None:
        raise ValueError(f"Skill {skill_name!r} missing from pinned pack")
    seat_spec = seat_doc.get("spec") or {}
    skill_spec = skill_doc.get("spec") or {}
    tools_idx = _tool_index(defs)
    allowed = _allowed_tools_for_assist(skill_spec, tools_idx)
    resources = list(seat_spec.get("resources") or [])
    skill_ceiling = str(skill_spec.get("ceiling") or "internal")
    if org is not None:
        ceiling = task_classification_ceiling(
            skill_ceiling,
            seat_doc,
            defs,
            org=org,
            workflow_name=workflow_name,
            participant_role=participant_role,
            person_id=person_id,
        )
    else:
        ceiling = skill_ceiling
    budget = contract_budget_block(skill_spec.get("budget") or {}, seat_limits)
    outputs = [
        {
            "artifact_type": at,
            "cardinality": "one",
            "schema_ref": f"ArtifactType/{at}",
        }
        for at in skill_spec.get("produces") or []
    ]
    contract: dict[str, Any] = {
        "schema_version": "aos.task_contract/1",
        "contract_id": ids.new_contract_id(),
        "contract_version": 1,
        "org_id": org_id,
        "instance_id": instance_id,
        "task_id": task_id,
        "kind": "assist",
        "template": "assist",
        "pack": {"name": pack_name, "version": pack_version, "digest": pack_digest},
        "seat": {"name": seat_name, "version": seat_version},
        "skill": {
            "name": skill_name,
            "version": int(skill_doc.get("metadata", {}).get("version", 1)),
            "instructions_sha256": _instructions_sha256(packs_dir, pack_name, skill_doc),
        },
        "work_type": work_type,
        "objective": f"Assist conversation turn for {participant_role}.",
        "on_behalf_of": {"role": participant_role, "person_id": person_id},
        "immutable_input_refs": [],
        "dependency_versions": {},
        "allowed_tools": allowed,
        "permission_scope": {"resources": resources, "classification_ceiling": ceiling},
        "budget": budget,
        "expected_outputs": outputs,
        "acceptance_checks": [],
        "approval_policy": {"policy": _gate_policy_ref(defs, workflow_name), "rules": []},
        "idempotency_key": f"{instance_id}:assist:{attempt_n}",
        "provenance_requirements": {"cite_sources": False, "record_input_hashes": True},
        "model": {
            "alias": (seat_spec.get("runtime") or {}).get("model_alias", "enterprise_reasoning"),
            "max_output_tokens": 4000,
        },
        "created_at": clock.now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    return finalize_assist_contract(contract, previous=None)


def build_task_contract(
    *,
    packs_dir: Path,
    pack_name: str,
    pack_version: int,
    pack_digest: str,
    defs: dict[str, dict[str, dict]],
    org_id: str,
    instance_id: str,
    task_id: str,
    seat_name: str,
    seat_version: int,
    seat_doc: dict[str, Any],
    workflow_name: str,
    template: dict[str, Any],
    participant_role: str,
    person_id: str | None,
    seat_limits: dict[str, Any],
    org: OrgModel | None = None,
) -> dict[str, Any]:
    skill_name = str(template["skill"])
    skill_doc = defs.get("Skill", {}).get(skill_name)
    if skill_doc is None:
        raise ValueError(f"Skill {skill_name!r} missing from pinned pack")
    seat_spec = seat_doc.get("spec") or {}
    skill_spec = skill_doc.get("spec") or {}
    tools_idx = _tool_index(defs)
    work_type = str(template["work_type"])
    allowed = _allowed_tools_for_task(skill_spec, work_type, tools_idx)
    resources = list(seat_spec.get("resources") or [])
    skill_ceiling = str(skill_spec.get("ceiling") or "internal")
    on_behalf_role = str(template.get("on_behalf_of") or participant_role)
    if org is not None:
        ceiling = task_classification_ceiling(
            skill_ceiling,
            seat_doc,
            defs,
            org=org,
            workflow_name=workflow_name,
            participant_role=on_behalf_role,
            person_id=person_id,
        )
    else:
        ceiling = skill_ceiling
    template_budget = template.get("budget")
    budget = contract_budget_block(
        skill_spec.get("budget") or {},
        seat_limits,
        template_override=template_budget,
    )
    outputs = [
        {
            "artifact_type": at,
            "cardinality": "one",
            "schema_ref": f"ArtifactType/{at}",
        }
        for at in skill_spec.get("produces") or []
    ]
    tpl_name = str(template["template"])
    contract: dict[str, Any] = {
        "schema_version": "aos.task_contract/1",
        "contract_id": ids.new_contract_id(),
        "contract_version": 1,
        "org_id": org_id,
        "instance_id": instance_id,
        "task_id": task_id,
        "kind": "task",
        "template": tpl_name,
        "pack": {"name": pack_name, "version": pack_version, "digest": pack_digest},
        "seat": {"name": seat_name, "version": seat_version},
        "skill": {
            "name": skill_name,
            "version": int(skill_doc.get("metadata", {}).get("version", 1)),
            "instructions_sha256": _instructions_sha256(packs_dir, pack_name, skill_doc),
        },
        "work_type": template["work_type"],
        "objective": f"Run workflow template {tpl_name}.",
        "on_behalf_of": {"role": participant_role, "person_id": person_id},
        "immutable_input_refs": [],
        "dependency_versions": {},
        "allowed_tools": allowed,
        "permission_scope": {"resources": resources, "classification_ceiling": ceiling},
        "budget": budget,
        "expected_outputs": outputs,
        "acceptance_checks": [],
        "approval_policy": {"policy": _gate_policy_ref(defs, workflow_name), "rules": []},
        "idempotency_key": f"{instance_id}:{tpl_name}:1",
        "provenance_requirements": {"cite_sources": False, "record_input_hashes": True},
        "model": {
            "alias": (seat_spec.get("runtime") or {}).get("model_alias", "enterprise_reasoning"),
            "max_output_tokens": 4000,
        },
        "created_at": clock.now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if template.get("verifier"):
        contract["verifier"] = template["verifier"]
    contract["contract_hash"] = contract_hash(contract)
    return contract


def _class_rank(label: str) -> int:
    return {"shareable": 0, "internal": 1, "restricted": 2}.get(label, 1)


def _min_classification(a: str, b: str) -> str:
    return a if _class_rank(a) <= _class_rank(b) else b


def resolve_assist_skill(seat_doc: dict, workflow_doc: dict, instance_state: str) -> str:
    seat_spec = seat_doc.get("spec") or {}
    states = (workflow_doc.get("spec") or {}).get("states") or {}
    state_spec = states.get(instance_state) or {}
    if state_spec.get("assist"):
        return str(state_spec["assist"])
    return str(seat_spec["assist_skill"])


def _seat_classification_ceiling(seat_doc: dict, defs: dict[str, dict[str, dict]]) -> str:
    seat_spec = seat_doc.get("spec") or {}
    resources = list(seat_spec.get("resources") or [])
    prof_ref = seat_spec.get("authority_profile") or ""
    prof_name = prof_ref.split("@")[0]
    prof = defs.get("Policy", {}).get(prof_name) or {}
    ceiling = "internal"
    if prof.get("spec", {}).get("type") == "authority_profile":
        for grant in prof.get("spec", {}).get("grants") or []:
            if grant.get("resource") in resources:
                c = grant.get("classification") or "internal"
                if _class_rank(c) > _class_rank(ceiling):
                    ceiling = c
    return ceiling


def participant_classification_ceiling(
    seat_doc: dict,
    defs: dict[str, dict[str, dict]],
    *,
    org: OrgModel,
    person_id: str,
) -> str:
    """Highest classification labels this person may receive in context and progress turns."""
    seat_ceiling = _seat_classification_ceiling(seat_doc, defs)
    person = org.people.get(person_id)
    if person is None:
        return "shareable"  # an unknown person gets the lowest label, never the Seat's
    clearance = seat_ceiling
    for role in person.roles:
        label = org.role_clearances.get(role, "internal")
        clearance = _min_classification(clearance, str(label))
    return clearance


_ASSIST_CONTRACT_IDENTITY_KEYS = frozenset(
    {"contract_id", "contract_version", "contract_hash", "created_at", "idempotency_key"}
)


def assist_contract_material_body(contract: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in contract.items() if k not in _ASSIST_CONTRACT_IDENTITY_KEYS}


def assist_contract_materially_unchanged(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    return assist_contract_material_body(current) == assist_contract_material_body(previous)


def finalize_assist_contract(
    contract: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Freeze contract hash and bump contract_version when the material body changes."""
    body = dict(contract)
    if previous and assist_contract_materially_unchanged(body, previous):
        return previous
    if previous and previous.get("contract_id"):
        body["contract_id"] = previous["contract_id"]
        body["contract_version"] = int(previous.get("contract_version") or 1) + 1
    else:
        body.setdefault("contract_version", 1)
    body["contract_hash"] = contract_hash(body)
    return body
