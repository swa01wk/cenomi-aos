"""Build and freeze TaskContract JSON from pinned pack definitions (M1)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..registry.kinds import EFFECT_COMMIT_WORK_TYPES, NATIVE_TOOLS
from ..registry.loader import load_pack
from . import clock, ids
from .org import OrgModel


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
            f"On-disk pack is v{meta.version}; the active seat is pinned to v{pack_version}."
            " Sync the pack from the Console (or run make sync-pack), publish the new version,"
            " and point the seat at it.",
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


def run_budget_block(run_budget: dict[str, Any] | None, seat_limits: dict[str, Any]) -> dict[str, Any]:
    """A Skill run's own budget (validated against the Seat's run limits at publish), else the Seat's attempt limits."""
    if not run_budget:
        return seat_budget_block(seat_limits)
    return {
        "tokens": int(run_budget["tokens"]),
        "cost_usd": float(run_budget["cost_usd"]),
        "time_s": int(run_budget["time_s"]),
        "steps": int(run_budget["steps"]),
        "actions": int(run_budget["actions"]),
        "retries": int(run_budget["retries"]),
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


def _tool_class(tool: dict) -> str:
    return str(tool.get("class") or tool.get("tool_class") or "read")


def _tool_grant(name: str, tool: dict, provider: str) -> dict[str, Any]:
    tool_class = _tool_class(tool)
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


def _allowed_tools(defs: dict[str, dict[str, dict]], skill_spec: dict, work_type: str) -> list[dict[str, Any]]:
    """Kernel tools plus what the Skill may request; committed effects only for effect-committing Work Types."""
    tools_idx = _tool_index(defs)
    allowed: list[dict[str, Any]] = []
    names: set[str] = set()
    for native in NATIVE_TOOLS:
        if native in ("save_draft", "ask_question"):
            allowed.append({"name": native, "kind": "kernel", "class": "kernel"})
            names.add(native)
    for tname in skill_spec.get("may_request") or []:
        if tname in names:
            continue
        if tname in _KERNEL_TOOL_NAMES:
            allowed.append({"name": tname, "kind": "kernel", "class": "kernel"})
        elif tname in tools_idx:
            prov, tool = tools_idx[tname]
            if _tool_class(tool) == "committed_effect" and work_type not in EFFECT_COMMIT_WORK_TYPES:
                continue
            allowed.append(_tool_grant(tname, tool, prov))
        else:
            continue
        names.add(tname)
    return allowed


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
    allowed = _allowed_tools(defs, skill_spec, work_type)
    resources = list(seat_spec.get("resources") or [])
    ceiling = _seat_classification_ceiling(seat_doc, defs)
    if org is not None:
        ceiling = participant_classification_ceiling(seat_doc, defs, org=org, person_id=person_id)
    budget = seat_budget_block(seat_limits)
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
    trigger_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skill_name = str(template["skill"])
    skill_doc = defs.get("Skill", {}).get(skill_name)
    if skill_doc is None:
        raise ValueError(f"Skill {skill_name!r} missing from pinned pack")
    seat_spec = seat_doc.get("spec") or {}
    skill_spec = skill_doc.get("spec") or {}
    work_type = str(template["work_type"])
    run = (skill_spec.get("runs") or {}).get(work_type) or {}
    allowed = _allowed_tools(defs, skill_spec, work_type)
    resources = list(seat_spec.get("resources") or [])
    ceiling = _min_classification(
        _seat_classification_ceiling(seat_doc, defs), role_clearance(defs, participant_role)
    )
    if run.get("classification_ceiling"):
        ceiling = _min_classification(ceiling, str(run["classification_ceiling"]))
    budget = run_budget_block(run.get("budget"), seat_limits)
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
        "work_type": work_type,
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
    if trigger_context:
        contract["trigger_context"] = trigger_context
    contract["contract_hash"] = contract_hash(contract)
    return contract


def _class_rank(label: str) -> int:
    return {"shareable": 0, "internal": 1, "restricted": 2}.get(label, 1)


def _min_classification(a: str, b: str) -> str:
    return a if _class_rank(a) <= _class_rank(b) else b


def role_clearance(defs: dict[str, dict[str, dict]], participant_role: str) -> str:
    """Highest classification among the artifact fields this participant role may see on the pack."""
    best = "shareable"
    for at in defs.get("ArtifactType", {}).values():
        spec = at.get("spec") or {}
        vis = (spec.get("visibility") or {}).get(participant_role)
        fields = spec.get("fields") or {}
        if vis is None or vis == "none":
            continue
        names = list(fields) if vis == "all" else [f for f in vis if f in fields]
        for name in names:
            label = (fields[name] or {}).get("classification") or spec.get("classification") or "internal"
            if _class_rank(label) > _class_rank(best):
                best = label
    return best


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
    resource_docs = defs.get("Resource", {})
    ceiling = "shareable"
    if prof.get("spec", {}).get("type") == "authority_profile":
        for grant in prof.get("spec", {}).get("grants") or []:
            res = grant.get("resource")
            if res in resources:
                c = ((resource_docs.get(res) or {}).get("spec") or {}).get("classification") or "internal"
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
    return _min_classification(seat_ceiling, person_clearance(list(person.roles) if person else []))


def person_clearance(org_roles: list[str]) -> str:
    """Highest classification a person may receive, from their org roles alone."""
    return "shareable" if list(org_roles) == ["end_user"] else "restricted"


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
