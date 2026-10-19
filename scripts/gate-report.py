"""Summarise `make gate` runs: each run's result and each check's pass rate across runs.

    python3 scripts/gate-report.py web/gate-results/run-*.json

Reads Playwright JSON reports; the gate test writes its checks to the "gate-scorecard" annotation.
Exits 1 unless every run passed.
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict


def gate_results(report: dict) -> list[dict]:
    """The gate test's entries (one per run), skipping stops 1–3. Each has its annotations and last result."""
    out: list[dict] = []

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            if not spec.get("title", "").startswith("M1 gate"):
                continue
            for t in spec.get("tests", []):
                results = t.get("results") or []
                result = results[-1] if results else {"status": t.get("status", "skipped")}
                # Runtime annotations are on the result (newer Playwright) or the test (older).
                notes = (result.get("annotations") or []) + (t.get("annotations") or [])
                out.append({"annotations": notes, "result": result})
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    return out


def chat_ran(path: str) -> bool:
    try:
        tests = gate_results(json.load(open(path, encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return False
    return any(t["result"].get("status") != "skipped" for t in tests)


def run_number(path: str) -> int:
    digits = "".join(ch for ch in path.rsplit("run-", 1)[-1] if ch.isdigit())
    return int(digits or 0)


def main(paths: list[str]) -> int:
    if not paths:
        print("No gate results found.")
        return 1
    tally: OrderedDict[str, list[bool]] = OrderedDict()
    passed = 0
    for path in paths:
        n = run_number(path)
        try:
            report = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"run {n}: no report ({exc})")
            continue
        tests = gate_results(report)
        if not tests or tests[0]["result"].get("status") == "skipped":
            print(f"run {n}: the chat didn't run (stops 1–3 failed; see the report above)")
            continue
        t = tests[0]
        status = t["result"].get("status")
        ok = status == "passed"
        passed += ok
        card: list[dict] = []
        for note in t.get("annotations", []):
            if note.get("type") == "gate-scorecard":
                card = json.loads(note.get("description") or "[]")
        for c in card:
            tally.setdefault(c["check"], []).append(bool(c["ok"]))
        line = f"run {n}: {'passed' if ok else 'FAILED'}"
        failed = [c for c in card if not c["ok"]]
        if failed:
            line += " — " + "; ".join(f"{c['check']} ({c['detail']})" if c["detail"] else c["check"] for c in failed)
        errors = t["result"].get("errors") or []
        if not ok and errors and not failed:
            line += " — stopped: " + (errors[0].get("message") or "").strip().splitlines()[0][:200]
        print(line)

    total = len(paths)
    print(f"\nM1 gate: {passed} of {total} run{'s' if total != 1 else ''} passed")
    if tally:
        print("\nChecks (passed / runs that reached them):")
        width = max(len(k) for k in tally)
        for check, results in tally.items():
            mark = "✓" if all(results) else "✗"
            print(f"  {mark} {check.ljust(width)}  {sum(results)}/{len(results)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--chat-ran"]:
        sys.exit(0 if args[1:] and chat_ran(args[1]) else 1)
    sys.exit(main(sorted(args, key=run_number)))
