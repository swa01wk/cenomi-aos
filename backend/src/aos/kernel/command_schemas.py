"""JSON Schemas for kernel commands exposed on ContextEnvelope.commands (M1-AG-03)."""

from __future__ import annotations

from typing import Any

from ..registry.kinds import ArtifactTypeSpec, FieldSpec


def _field_json_type(field: FieldSpec) -> dict[str, Any]:
    t = field.type
    if t == "integer":
        return {"type": "integer"}
    if t in ("number", "money"):
        return {"type": "number"}
    if t == "date":
        return {"type": "string", "format": "date"}
    if t == "datetime":
        return {"type": "string", "format": "date-time"}
    if t == "list":
        return {"type": "array"}
    if t == "boolean":
        return {"type": "boolean"}
    if t == "object":
        return {"type": "object"}
    return {"type": "string"}


def _field_schema(field: FieldSpec) -> dict[str, Any]:
    schema = _field_json_type(field)
    notes = [field.description.strip()] if field.description.strip() else []
    if field.required:
        notes.append("Required before the output can be confirmed.")
    if notes:
        schema["description"] = " ".join(notes)
    return schema


def artifact_content_schema(type_spec: ArtifactTypeSpec) -> dict[str, Any]:
    """Field types and descriptions; no required list (partial drafts; completeness is verifier-owned)."""
    properties: dict[str, Any] = {}
    for name, field in type_spec.fields.items():
        properties[name] = _field_schema(field)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if type_spec.row_based:
        return {
            "type": "object",
            "required": ["rows"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": properties,
                        "additionalProperties": False,
                    },
                }
            },
            "additionalProperties": False,
        }
    return schema


def _key_property(item_keys: list[str]) -> dict[str, Any]:
    names = " or ".join(sorted(set(item_keys)))
    return {
        "type": "string",
        "description": f"One draft per item: the draft's {names} value. Drafts with different keys are separate.",
    }


def save_draft_command_schema(contract: dict[str, Any], defs: dict[str, dict[str, dict]]) -> dict[str, Any]:
    outputs = [
        o for o in (contract.get("expected_outputs") or []) if isinstance(o, dict) and o.get("artifact_type")
    ]
    if len(outputs) == 1:
        at_name = str(outputs[0]["artifact_type"])
        from .artifacts import parse_artifact_type

        at = parse_artifact_type(defs, at_name)
        content_schema = artifact_content_schema(at.spec)
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["content"],
            "properties": {"content": content_schema},
            "additionalProperties": False,
        }
        if at.spec.item_key:
            schema["required"] = ["key", "content"]
            schema["properties"]["key"] = _key_property([at.spec.item_key])
        return schema
    content_schemas = []
    item_keys: list[str] = []
    for out in outputs:
        at_name = str(out["artifact_type"])
        from .artifacts import parse_artifact_type

        at = parse_artifact_type(defs, at_name)
        content_schemas.append(artifact_content_schema(at.spec))
        if at.spec.item_key:
            item_keys.append(at.spec.item_key)
    content_prop: dict[str, Any] = {"type": "object"}
    if len(content_schemas) == 1:
        content_prop = content_schemas[0]
    elif content_schemas:
        content_prop = {"anyOf": content_schemas}
    types = [str(o["artifact_type"]) for o in outputs]
    type_prop: dict[str, Any] = {"type": "string"}
    if types:
        type_prop = {"enum": types}
    properties: dict[str, Any] = {"artifact_type": type_prop, "content": content_prop}
    if item_keys:
        properties["key"] = _key_property(item_keys)
    return {
        "type": "object",
        "required": ["artifact_type", "content"],
        "properties": properties,
        "additionalProperties": False,
    }


def submit_command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string", "description": "One or two plain sentences for people."}},
        "additionalProperties": False,
    }


def ask_question_command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["questions"],
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string"},
            },
            "preamble": {"type": "string"},
        },
        "additionalProperties": False,
    }


def enrich_command_schema(
    name: str,
    contract: dict[str, Any],
    defs: dict[str, dict[str, dict]],
    entry: dict[str, Any],
) -> dict[str, Any]:
    if name == "read_artifact":
        return entry
    if name == "save_draft":
        entry["input_schema"] = save_draft_command_schema(contract, defs)
        entry["description"] = (
            "Save a new draft version of the job's output. Send the fields you have learned; fields you leave out, or "
            "send empty, keep their current values. The requester sees the draft next to the chat, so don't repeat it "
            "in your reply."
        )
        return entry
    if name == "ask_question":
        entry["input_schema"] = ask_question_command_schema()
        entry["description"] = (
            "Ask the requester up to three questions and end this reply; their answer starts your next one. "
            "preamble is one short sentence shown before the questions."
        )
        return entry
    if name == "submit":
        entry["input_schema"] = submit_command_schema()
        entry["description"] = "Finish the attempt with a short summary once outputs are saved."
        return entry
    return entry
