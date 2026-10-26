"""leak_check: no protected value of any artifact in the job appears in a shareable output field.

Protected means a field the pack itself marks `internal` or `restricted` (such as a budget or a quoted price). A type's
default classification bounds what a Task's context may carry; it doesn't make every value secret (a supplier's name
in its own request for quotation is the point of the message).

Numbers match after dropping currency words and symbols, thousands separators and spaces, so 40,000, SAR 40000 and
40k all match 40000. Text matches case-insensitively. Findings name fields, never the value; a per-item output is
named with its item key, e.g. `rfq_email[SUP-1].body`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from ..kernel.artifacts import parse_artifact_type
from ..registry.kinds import ArtifactTypeSpec
from . import _records

PROTECTED = ("internal", "restricted")
MIN_TEXT_LEN = 3

_CURRENCY = re.compile(r"(?i)(?:\b(?:sar|sr|usd|aed|eur|gbp|riyals?|dollars?)\b|(?:sar|usd|aed|eur|gbp)(?=\d)|[$€£﷼])")
_GROUPED = re.compile(r"(?<![\w.])(\d{1,3}(?:[,  ]\d{3})+)(?:\.(\d+))?\s?([kKmM])?(?!\w)")
_PLAIN = re.compile(r"(?<![\w.])(\d+)(?:\.(\d+))?\s?([kKmM])?(?!\w)")
_NUMERIC_TEXT = re.compile(r"^\s*\d[\d,  ]*(?:\.\d+)?\s?[kKmM]?\s*$")
_SCALE = {"k": 1_000, "m": 1_000_000}


@dataclass(frozen=True)
class Protected:
    artifact_type: str
    field: str
    numbers: frozenset[float]
    texts: frozenset[str]


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


def numbers_in(text: str) -> set[float]:
    """Every number a reader could take from the text, normalised."""
    clean = _CURRENCY.sub(" ", text)
    found: set[float] = set()
    for pattern in (_GROUPED, _PLAIN):
        for whole, frac, scale in pattern.findall(clean):
            value = float(re.sub(r"[,  ]", "", whole) + (f".{frac}" if frac else ""))
            found.add(value * _SCALE.get(scale.lower(), 1) if scale else value)
    return found


def _values(value: Any) -> tuple[set[float], set[str]]:
    numbers: set[float] = set()
    texts: set[str] = set()
    if isinstance(value, bool) or value is None:
        return numbers, texts
    if isinstance(value, (int, float)):
        numbers.add(float(value))
    elif isinstance(value, str):
        stripped = _CURRENCY.sub(" ", value)
        if _NUMERIC_TEXT.match(stripped):
            numbers |= numbers_in(stripped)
        elif len(value.strip()) >= MIN_TEXT_LEN:
            texts.add(_fold(value))
    elif isinstance(value, dict):
        if "amount" in value:
            return _values(value["amount"])
        for v in value.values():
            n, t = _values(v)
            numbers |= n
            texts |= t
    elif isinstance(value, list):
        for v in value:
            n, t = _values(v)
            numbers |= n
            texts |= t
    return numbers, texts


def _records_of(content: dict[str, Any], spec: ArtifactTypeSpec) -> list[dict[str, Any]]:
    if spec.row_based:
        return [r for r in content.get("rows") or [] if isinstance(r, dict)]
    return [content]


def protected_values(artifact_type: str, content: dict[str, Any], spec: ArtifactTypeSpec) -> list[Protected]:
    marked = [name for name, f in spec.fields.items() if f.classification in PROTECTED]
    out: list[Protected] = []
    for record in _records_of(content, spec):
        for name in marked:
            numbers, texts = _values(record.get(name))
            if numbers or texts:
                out.append(Protected(artifact_type, name, frozenset(numbers), frozenset(texts)))
    return out


def shareable_text(content: dict[str, Any], spec: ArtifactTypeSpec) -> dict[str, list[str]]:
    """Output field name -> the text a reader of that field sees."""
    fields: dict[str, list[str]] = {}
    for record in _records_of(content, spec):
        for name, f in spec.fields.items():
            if (f.classification or spec.classification) != "shareable" or record.get(name) is None:
                continue
            value = record[name]
            fields.setdefault(name, []).append(value if isinstance(value, str) else json.dumps(value))
    return fields


def check_output(output_type: str, fields: dict[str, list[str]], protected: list[Protected]) -> list[str]:
    findings: list[str] = []
    for field, texts in fields.items():
        folded = [_fold(t) for t in texts]
        numbers = set().union(*(numbers_in(t) for t in texts)) if texts else set()
        leaked = sorted(
            {
                f"{p.artifact_type}.{p.field}"
                for p in protected
                if p.numbers & numbers or any(v in t for v in p.texts for t in folded)
            }
        )
        findings.extend(f"{output_type}.{field} contains the value of {name}." for name in leaked)
    return findings


async def _instance_protected(conn: AsyncConnection, instance_id: str, defs: dict) -> list[Protected]:
    cur = await conn.execute(
        "select a.artifact_type, v.content from work.artifact_versions v"
        " join work.artifacts a on a.id = v.artifact_id where a.instance_id = %s",
        (instance_id,),
    )
    specs: dict[str, ArtifactTypeSpec] = {}
    out: list[Protected] = []
    for artifact_type, raw in await cur.fetchall():
        if artifact_type not in specs:
            specs[artifact_type] = parse_artifact_type(defs, artifact_type).spec
        content = json.loads(raw) if isinstance(raw, str) else raw
        out.extend(protected_values(artifact_type, content or {}, specs[artifact_type]))
    return out


async def verify(conn: AsyncConnection, gate: Any, result: dict[str, Any], defs: dict) -> tuple[str, list[str]]:
    protected = await _instance_protected(conn, gate.instance_id, defs)
    findings: list[str] = []
    for output in await _records.outputs(conn, result):
        spec = parse_artifact_type(defs, output.artifact_type).spec
        label = output.artifact_type
        if spec.item_key:
            label = f"{label}[{output.content.get(spec.item_key)}]"
        findings.extend(check_output(label, shareable_text(output.content, spec), protected))
    return ("REWORK", findings) if findings else ("PASS", [])
