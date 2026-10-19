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


def _current_content(
    envelope: dict[str, Any], artifact_type: str, prior: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The draft's current content, or None when the envelope can't show all of it (fields were redacted)."""
    for red in envelope.get("redactions") or []:
        if isinstance(red, dict) and red.get("artifact_type") == artifact_type:
            return None
    if prior and isinstance(prior.get("content"), dict):
        return dict(prior["content"])  # saved earlier in this attempt; newer than the envelope may be
    for art in envelope.get("artifacts") or []:
        if isinstance(art, dict) and art.get("artifact_type") == artifact_type and isinstance(art.get("content"), dict):
            return dict(art["content"])
    return {}


def merge_draft_content(current: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    """A save is an update: fields the model sends replace the current ones, fields it leaves out are kept, and null
    clears a field. When the current content isn't fully visible, the update is saved as it is."""
    merged = {**(current or {}), **update}
    return {k: v for k, v in merged.items() if v is not None}


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
        "content": merge_draft_content(_current_content(envelope, artifact_type, prior), content),
        "inputs": inputs,
        "key": key,
    }
    if artifact_id:
        body["artifact_id"] = artifact_id
        if base_version is not None:
            body["base_version"] = int(base_version)
    return body
