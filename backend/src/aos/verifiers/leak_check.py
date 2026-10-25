"""Verifier leak_check: internal/restricted values must not appear in shareable outputs."""

from __future__ import annotations

import re
from typing import Any, Literal

from ._fields import field_classification, iter_field_values, money_number

Verdict = Literal["PASS", "REWORK", "FAIL"]

_CURRENCY_WORDS = re.compile(r"\b(sar|usd|eur|gbp|riyals?)\b", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_number_token(text: str) -> int | None:
    t = text.strip().lower()
    t = _CURRENCY_WORDS.sub(" ", t)
    t = t.replace(",", "").replace(" ", "")
    mult = 1
    if t.endswith("k"):
        mult = 1000
        t = t[:-1]
    t = re.sub(r"[^0-9.]", "", t)
    if not t:
        return None
    try:
        val = float(t)
    except ValueError:
        return None
    return int(val * mult) if mult != 1 else int(val) if val == int(val) else None


def _extract_numbers(text: str) -> set[int]:
    """Whole numeric tokens in text (after normalisation), not digit substrings of larger numbers."""
    lowered = text.lower()
    lowered = _CURRENCY_WORDS.sub(" ", lowered)
    tokens = re.split(r"(\d[\d,.\s]*k?)", lowered, flags=re.I)
    out: set[int] = set()
    for tok in tokens:
        if not tok or not re.search(r"\d", tok):
            continue
        n = _normalize_number_token(tok)
        if n is not None:
            out.add(n)
    return out


def _collect_sensitive(
    instance_artifacts: list[dict[str, Any]],
    artifact_types: dict[str, dict[str, Any]],
) -> list[tuple[str, str, Any]]:
    """(artifact_type, field_name, value) for internal and restricted fields."""
    out: list[tuple[str, str, Any]] = []
    for art in instance_artifacts:
        atype = str(art.get("artifact_type") or "")
        content = art.get("content")
        if not isinstance(content, dict):
            continue
        spec = artifact_types.get(atype) or {}
        row_based = bool(spec.get("row_based"))
        for fname, val in iter_field_values(content, row_based=row_based):
            if val is None or val == "" or val == []:
                continue
            cls = field_classification(atype, fname, artifact_types)
            if cls in ("internal", "restricted"):
                out.append((atype, fname, val))
    return out


def _shareable_outputs(outputs: list[dict[str, Any]], artifact_types: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """(artifact_type, field_name, text) for shareable output fields."""
    rows: list[tuple[str, str, str]] = []
    for out in outputs:
        atype = str(out.get("artifact_type") or "")
        spec = artifact_types.get(atype) or {}
        content = out.get("content")
        if not isinstance(content, dict):
            continue
        row_based = bool(spec.get("row_based"))
        for fname, val in iter_field_values(content, row_based=row_based):
            if val is None:
                continue
            if field_classification(atype, fname, artifact_types) != "shareable":
                continue
            if isinstance(val, str):
                text = val
            elif isinstance(val, (int, float)):
                text = str(val)
            else:
                text = str(val)
            rows.append((atype, fname, text))
    return rows


def _sensitive_numbers(val: Any) -> list[int]:
    nums: list[int] = []
    if isinstance(val, str):
        for n in _extract_numbers(val):
            nums.append(n)
        n = money_number(val)
        if n is not None:
            nums.append(int(n) if float(n) == int(n) else int(n))
    elif isinstance(val, (int, float)) and not isinstance(val, bool):
        nums.append(int(val))
    return list(dict.fromkeys(nums))


def _sensitive_phrases(val: Any) -> list[str]:
    if not isinstance(val, str):
        return []
    phrase = val.strip()
    if len(phrase) < 4:
        return []
    return [phrase.lower()]


def verify(inp: dict[str, Any]) -> tuple[Verdict, list[str]]:
    artifact_types = inp.get("artifact_types") or {}
    sensitive = _collect_sensitive(inp.get("instance_artifacts") or [], artifact_types)
    outputs = _shareable_outputs(inp.get("outputs") or [], artifact_types)

    findings: list[str] = []
    for out_type, out_field, out_text in outputs:
        out_lower = out_text.lower()
        out_numbers = _extract_numbers(out_text)
        for src_type, src_field, src_val in sensitive:
            for num in _sensitive_numbers(src_val):
                if abs(num) < 100:
                    continue
                if num in out_numbers:
                    findings.append(f"{out_field}: leaks {src_type}.{src_field}")
                    break
            else:
                for phrase in _sensitive_phrases(src_val):
                    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
                    if re.search(pattern, out_lower):
                        findings.append(f"{out_field}: leaks {src_type}.{src_field}")
                        break

    if findings:
        return "REWORK", findings
    return "PASS", []
