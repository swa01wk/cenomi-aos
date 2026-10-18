"""Build and freeze TaskContract JSON from pinned pack definitions (M1)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..registry.kinds import NATIVE_TOOLS
from ..registry.loader import load_pack
from . import ids


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


def max_attempts_from_budget(budget: dict[str, Any]) -> int:
    return int(budget["retries"]) + 1


def _tool_index(defs: dict[str, dict[str, dict]]) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for prov_name, prov in defs.get("ToolProvider", {}).items():
        for tname, tool in (prov.get("spec") or {}).get("tools", {}).items():
            out[tname] = (prov_name, tool)
    return out


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
) -> dict[str, Any]:
    skill_doc = defs.get("Skill", {}).get(skill_name)
    if skill_doc is None:
        raise ValueError(f"Skill {skill_name!r} missing from pinned pack")
    seat_spec = seat_doc.get("spec") or {}
    skill_spec = skill_doc.get("spec") or {}
    tools_idx = _tool_index(defs)
    allowed: list[dict[str, Any]] = []
    for native in NATIVE_TOOLS:
        if native in ("save_draft", "ask_question"):
            allowed.append({"name": native, "kind": "kernel", "class": "kernel"})
    for tname in skill_spec.get("may_request") or []:
        if tname in _KERNEL_TOOL_NAMES:
            allowed.append({"name": tname, "kind": "kernel", "class": "kernel"})
        elif tname in tools_idx:
            prov, tool = tools_idx[tname]
            allowed.append(_tool_grant(tname, tool, prov))
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
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    contract["contract_hash"] = contract_hash(contract)
    return contract


def _class_rank(label: str) -> int:
    return {"shareable": 0, "internal": 1, "restricted": 2}.get(label, 1)
