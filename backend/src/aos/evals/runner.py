"""Run EvalSuite definitions for Seat testing without holding a database transaction.

M1 executes suites in-process with structural checks only; behavioural expectations are deferred.
M1-BE-05 replaces the caller with worker-lane execution using the same result shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..registry.loader import parse_yaml

DEFER_POLICY = "policy engine is M3"
DEFER_CONTEXT = "context assembler is M1-BE-06"
DEFER_WORKFLOW = "workflow simulation is M2"
DEFER_EFFECTS = "governed effects are M3"


@dataclass(frozen=True)
class SuiteRunResult:
    passed: int
    total: int
    status: str
    detail: dict[str, Any]


def _artifact_field_names(defs: dict[str, dict[str, dict]]) -> set[str]:
    names: set[str] = set()
    for doc in defs.get("ArtifactType", {}).values():
        fields = (doc.get("spec") or {}).get("fields") or {}
        if isinstance(fields, dict):
            names.update(fields.keys())
    return names


def _check_record(
    checks: list[dict[str, Any]], *, name: str, passed: bool, detail: str = ""
) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _defer_expectations(expect: dict[str, Any], suite_kind: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if suite_kind == "refusals":
        if "policy_result" in expect:
            out.append({"key": "policy_result", "status": "deferred", "reason": DEFER_POLICY})
        if "context_excludes_fields" in expect:
            out.append({"key": "context_excludes_fields", "status": "deferred", "reason": DEFER_CONTEXT})
    elif suite_kind == "dry_run":
        if "final_state" in expect:
            out.append({"key": "final_state", "status": "deferred", "reason": DEFER_WORKFLOW})
        if "unapproved_effects" in expect:
            out.append({"key": "unapproved_effects", "status": "deferred", "reason": DEFER_EFFECTS})
    return out


def run_refusals_suite(*, suite_spec: dict[str, Any], defs: dict[str, dict[str, dict]]) -> SuiteRunResult:
    spec = suite_spec.get("spec") or {}
    expect = spec.get("expect") or {}
    checks: list[dict[str, Any]] = []
    cases = spec.get("cases") or []
    known_fields = _artifact_field_names(defs)

    for i, case in enumerate(cases):
        ok = isinstance(case, str) and bool(case.strip())
        _check_record(
            checks,
            name=f"case_{i}_well_formed",
            passed=ok,
            detail="" if ok else "each case must be a non-empty string",
        )

    excluded = expect.get("context_excludes_fields") or []
    if excluded:
        missing = [f for f in excluded if f not in known_fields]
        fields_ok = not missing
        _check_record(
            checks,
            name="context_excludes_fields_exist",
            passed=fields_ok,
            detail="" if fields_ok else f"unknown fields: {', '.join(missing)}",
        )

    expectations = _defer_expectations(expect, "refusals")
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    status = "passed" if passed == total else "failed"
    return SuiteRunResult(
        passed=passed,
        total=total,
        status=status,
        detail={
            "checks": checks,
            "expectations": expectations,
            "deferred_count": len(expectations),
        },
    )


def run_dry_run_suite(
    *,
    suite_spec: dict[str, Any],
    pack_root: Path,
    suite_file: str | None,
) -> SuiteRunResult:
    spec = suite_spec.get("spec") or {}
    expect = spec.get("expect") or {}
    checks: list[dict[str, Any]] = []
    script_name = spec.get("script")
    script_ok = False
    script_detail = ""
    if not script_name:
        script_detail = "suite has no script"
    else:
        folder = Path(suite_file).parent if suite_file else Path("evals")
        script_path = (pack_root / folder / script_name).resolve()
        try:
            script_path.relative_to(pack_root.resolve())
        except ValueError:
            script_detail = "script path escapes the pack root"
        else:
            if not script_path.is_file():
                script_detail = f"script {script_name!r} not found"
            else:
                try:
                    parse_yaml(script_path.read_bytes())
                    script_ok = True
                except yaml.YAMLError as exc:
                    script_detail = f"script is not valid YAML: {exc}"

    _check_record(checks, name="script_resolves", passed=script_ok, detail=script_detail)
    expectations = _defer_expectations(expect, "dry_run")
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    status = "passed" if passed == total else "failed"
    return SuiteRunResult(
        passed=passed,
        total=total,
        status=status,
        detail={
            "checks": checks,
            "expectations": expectations,
            "deferred_count": len(expectations),
        },
    )


def run_suite(
    *,
    suite_name: str,
    suite_spec: dict[str, Any],
    defs: dict[str, dict[str, dict]],
    pack_root: Path,
    suite_file: str | None = None,
) -> SuiteRunResult:
    """Execute one EvalSuite and return scored results (no I/O besides pack files)."""
    spec = suite_spec.get("spec") or {}
    if spec.get("script"):
        return run_dry_run_suite(suite_spec=suite_spec, pack_root=pack_root, suite_file=suite_file)
    if spec.get("cases"):
        return run_refusals_suite(suite_spec=suite_spec, defs=defs)
    return SuiteRunResult(
        0,
        0,
        "failed",
        {
            "checks": [{"name": "suite_shape", "passed": False, "detail": "suite needs cases or a script"}],
            "expectations": [],
            "deferred_count": 0,
        },
    )
