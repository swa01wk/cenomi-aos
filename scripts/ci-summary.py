#!/usr/bin/env python3
"""Turn CI result files into a GitHub job summary (and annotations), so results read on the run page.

    ci-summary.py validate validate.json          aos validate --json; exits 1 on errors (and on warnings when
                                                  CI_STRICT_WARNINGS=1)
    ci-summary.py playwright results.json [--title T] [--min-rate R]
                                                  Playwright JSON reporter; pass rate per project and failures;
                                                  with --min-rate, exits 1 when a journey project is below R
    ci-summary.py evals eval-results/report.json  aos eval report; pass rates per skill against thresholds

`validate` and `playwright --min-rate` set the exit code; otherwise the test step itself is the gate.
Standard library only, so it runs on a bare runner.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def emit(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(markdown.rstrip() + "\n\n")
    else:
        print(markdown)


def annotate(level: str, message: str, file: str | None = None, title: str | None = None) -> None:
    props = []
    if file:
        props.append(f"file={file}")
    if title:
        props.append(f"title={title}")
    head = f"::{level} {','.join(props)}" if props else f"::{level}"
    print(f"{head}::{message.replace('%', '%25').replace(chr(10), '%0A')}")


def load(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        annotate("warning", f"{path} is not valid JSON: {exc}")
        return None


def cmd_validate(path: str) -> int:
    report = load(path)
    if report is None:
        annotate("error", f"no validate report at {path}", title="aos validate")
        return 1
    errors = report.get("errors") or []
    warnings = report.get("warnings") or []
    pack = report.get("pack", "pack")
    for item in errors + warnings:
        level = "error" if item in errors else "warning"
        annotate(level, f"{item.get('code')}: {item.get('message')} ({item.get('path', '')})",
                 file=f"packs/{pack}/{item.get('file', '')}", title="aos validate")
    lines = [f"### aos validate · {pack} v{report.get('version')}",
             f"{len(errors)} errors, {len(warnings)} warnings", ""]
    if errors or warnings:
        lines += ["| Severity | Code | File | Message |", "| --- | --- | --- | --- |"]
        for item in errors + warnings:
            sev = "error" if item in errors else "warning"
            lines.append(f"| {sev} | {item.get('code')} | `{item.get('file')}` | {item.get('message')} |")
    emit("\n".join(lines))
    strict = os.environ.get("CI_STRICT_WARNINGS") == "1"
    return 1 if errors or (strict and warnings) else 0


def _walk(suite: dict, trail: list[str], out: list[dict]) -> None:
    title = suite.get("title") or ""
    here = trail + ([title] if title and not title.endswith(".ts") else [])
    for spec in suite.get("specs", []):
        for test in spec.get("tests", []):
            results = test.get("results") or []
            last = results[-1] if results else {}
            out.append({
                "title": " › ".join(here + [spec.get("title", "")]),
                "file": spec.get("file") or suite.get("file"),
                "project": test.get("projectName", ""),
                "status": test.get("status") or last.get("status", "unknown"),
                "duration_s": round(sum(r.get("duration", 0) for r in results) / 1000, 1),
                "error": ((last.get("error") or {}).get("message") or "").strip(),
            })
    for child in suite.get("suites", []):
        _walk(child, here, out)


def cmd_playwright(path: str, title: str, min_rate: float | None = None) -> int:
    report = load(path)
    if report is None:
        emit(f"### {title}\nNo Playwright results (no specs ran or the run stopped before reporting).")
        return 1 if min_rate is not None else 0
    tests: list[dict] = []
    for suite in report.get("suites", []):
        _walk(suite, [], tests)
    setup = {"stop-01", "stop-02", "stop-03"}
    by_project: dict[str, list[dict]] = defaultdict(list)
    for t in tests:
        by_project[t["project"]].append(t)
    below: list[str] = []
    lines = [f"### {title}", "| Project | Passed | Total | Pass rate | Time (min) |", "| --- | --- | --- | --- | --- |"]
    for project, items in sorted(by_project.items(), key=lambda kv: (kv[0] in setup, kv[0])):
        ok = sum(1 for t in items if t["status"] in ("expected", "flaky", "passed"))
        total = sum(1 for t in items if t["status"] != "skipped")
        rate = f"{ok / total:.0%}" if total else "–"
        mins = round(sum(t["duration_s"] for t in items) / 60, 1)
        label = f"{project} (setup)" if project in setup else project
        if min_rate is not None and project not in setup and (not total or ok / total < min_rate):
            below.append(f"{project} {ok}/{total}")
        lines.append(f"| {label} | {ok} | {total} | {rate} | {mins} |")
    failed = [t for t in tests if t["status"] in ("unexpected", "failed", "timedOut")]
    if failed:
        lines += ["", "**Failures**", ""]
        for t in failed:
            first = t["error"].splitlines()[0][:200] if t["error"] else "no message"
            lines.append(f"- `{t['project']}` {t['title']}: {first}")
    if not tests:
        lines.append("| – | 0 | 0 | – | – |")
    if min_rate is not None:
        verdict = "below" if below or not tests else "meets"
        lines += ["", f"Required pass rate {min_rate:.0%}: **{verdict}**" + (f" ({', '.join(below)})" if below else "")]
        if below:
            annotate("error", f"pass rate below {min_rate:.0%}: {', '.join(below)}", title=title)
    emit("\n".join(lines))
    return 1 if min_rate is not None and (below or not tests) else 0


def cmd_evals(path: str) -> int:
    report = load(path)
    if report is None:
        emit("### Agent evals\nNo eval report (runner not built yet, or the run stopped before writing it).")
        return 0
    th = report.get("thresholds") or {}
    lines = [
        f"### Agent evals · {report.get('mode', '?')} model · {report.get('runs', '?')} run(s) per scenario",
        f"Thresholds: must-checks {th.get('must', 1.0):.0%}, quality {th.get('quality', 0.8):.0%}, "
        f"safety failures {th.get('safety_failures', 0)}",
        "",
        "| Skill | Scenarios | Must | Quality | Safety failures | Result |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for skill in report.get("skills", []):
        sc = skill.get("scenarios") or []
        must = min((s.get("must_pass_rate", 0.0) for s in sc), default=0.0)
        qual = min((s.get("quality_pass_rate", 1.0) for s in sc), default=1.0)
        safety = sum(int(s.get("safety_failures", 0)) for s in sc)
        ok = must >= th.get("must", 1.0) and qual >= th.get("quality", 0.8) and safety <= th.get("safety_failures", 0)
        lines.append(f"| `{skill.get('skill')}` | {len(sc)} | {must:.0%} | {qual:.0%} | {safety} | "
                     f"{'pass' if ok else '**fail**'} |")
        if not ok:
            annotate("error", f"{skill.get('skill')}: must {must:.0%}, quality {qual:.0%}, safety {safety}",
                     title="agent evals")
    emit("\n".join(lines))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    mode, path = argv[0], argv[1]
    if mode == "validate":
        return cmd_validate(path)
    if mode == "playwright":
        title = argv[argv.index("--title") + 1] if "--title" in argv else "Playwright"
        rate = float(argv[argv.index("--min-rate") + 1]) if "--min-rate" in argv else None
        return cmd_playwright(path, title, rate)
    if mode == "evals":
        return cmd_evals(path)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
