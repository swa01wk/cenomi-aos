"""Summarise `make gate` runs: each run's result and each check's pass rate across runs.

    python3 scripts/gate-report.py web/gate-results/run-*.json

Reads Playwright JSON reports; the gate test writes its checks to the "gate-scorecard" annotation.
Exits 1 unless every run passed its must-checks and each quality check passed in at least GATE_MIN_QUALITY
(default 0.8) of the runs that reached it.
"""

from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict

# Share of runs each quality check must pass (must-checks always need every run).
MIN_QUALITY = float(os.environ.get("GATE_MIN_QUALITY", "0.8"))


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
    kinds: dict[str, str] = {}
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
        # Only must-checks (and hard stops) fail the test; quality misses are listed but don't fail the run.
        ok = t["result"].get("status") == "passed"
        passed += ok
        card: list[dict] = []
        for note in t.get("annotations", []):
            if note.get("type") == "gate-scorecard":
                card = json.loads(note.get("description") or "[]")
        for c in card:
            tally.setdefault(c["check"], []).append(bool(c["ok"]))
            kinds[c["check"]] = c.get("kind", "must")
        def label(c: dict) -> str:
            return f"{c['check']} ({c['detail']})" if c["detail"] else c["check"]

        line = f"run {n}: {'passed' if ok else 'FAILED'}"
        must = [c for c in card if not c["ok"] and c.get("kind", "must") == "must"]
        missed = [c for c in card if not c["ok"] and c.get("kind") == "quality"]
        if must:
            line += " — " + "; ".join(label(c) for c in must)
        errors = t["result"].get("errors") or []
        if not ok and errors and not must:
            line += " — stopped: " + (errors[0].get("message") or "").strip().splitlines()[0][:200]
        if missed:
            line += " · quality misses: " + "; ".join(label(c) for c in missed)
        print(line)

    total = len(paths)
    print(f"\nRuns: {passed} of {total} passed every must-check")
    low: list[str] = []
    if tally:
        width = max(len(k) for k in tally)
        for kind, heading in (("must", "Must pass in every run"), ("quality", f"Quality: at least {MIN_QUALITY:.0%} of runs")):
            rows = [(k, r) for k, r in tally.items() if kinds.get(k, "must") == kind]
            if not rows:
                continue
            print(f"\n{heading} (passed / runs that reached them):")
            for check, results in rows:
                rate = sum(results) / len(results)
                good = all(results) if kind == "must" else rate >= MIN_QUALITY
                if kind == "quality" and not good:
                    low.append(check)
                print(f"  {'✓' if good else '✗'} {check.ljust(width)}  {sum(results)}/{len(results)}")
    gate_ok = passed == total and not low
    print(f"\nM1 gate: {'PASSED' if gate_ok else 'FAILED'}", end="")
    if not gate_ok:
        reasons = []
        if passed != total:
            reasons.append(f"{total - passed} run(s) failed a must-check")
        if low:
            reasons.append(f"below {MIN_QUALITY:.0%}: {', '.join(low)}")
        print(" — " + "; ".join(reasons), end="")
    print()
    return 0 if gate_ok else 1

if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--chat-ran"]:
        sys.exit(0 if args[1:] and chat_ran(args[1]) else 1)
    sys.exit(main(sorted(args, key=run_number)))
