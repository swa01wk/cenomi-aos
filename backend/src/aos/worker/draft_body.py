"""Build kernel DraftRequest bodies from model save_draft tool args."""

from __future__ import annotations

from typing import Any


def _expected_output_types(contract: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in contract.get("expected_outputs") or []:
        if isinstance(item, dict) and item.get("artifact_type"):
            out.append(str(item["artifact_type"]))
    return out


def _artifact_refs_from_envelope(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for art in envelope.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        aid = art.get("artifact_id")
        ver = art.get("version")
        if aid and ver is not None:
            refs.append({"artifact_id": str(aid), "version": int(ver)})
    return refs


def build_save_draft_body(
    *,
    contract: dict[str, Any],
    envelope: dict[str, Any],
    model_args: dict[str, Any],
    saved_in_attempt: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Model supplies content (and artifact_type only when the contract has multiple outputs)."""
    types = _expected_output_types(contract)
    if len(types) == 1:
        artifact_type = types[0]
    else:
        artifact_type = str(model_args.get("artifact_type") or "")
        if artifact_type not in types:
            raise ValueError(f"artifact_type must be one of {types!r}")
    content = model_args.get("content")
    if not isinstance(content, dict):
        raise ValueError("content must be an object")

    inputs = _artifact_refs_from_envelope(envelope)
    key = ""
    artifact_id = None
    base_version = None

    for art in envelope.get("artifacts") or []:
        if isinstance(art, dict) and art.get("artifact_type") == artifact_type:
            artifact_id = art.get("artifact_id")
            base_version = art.get("version")
            break

    prior = saved_in_attempt.get(artifact_type)
    if prior:
        artifact_id = prior.get("artifact_id") or artifact_id
        base_version = prior.get("version")

    body: dict[str, Any] = {
        "artifact_type": artifact_type,
        "content": content,
        "inputs": inputs,
        "key": key,
    }
    if artifact_id:
        body["artifact_id"] = artifact_id
        if base_version is not None:
            body["base_version"] = int(base_version)
    return body
