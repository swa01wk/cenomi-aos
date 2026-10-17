"""The ``aos`` command line. M0 ships ``validate``; simulate, test, diff and publish arrive in later milestones."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .registry import validate_pack


def _validate(args: argparse.Namespace) -> int:
    org = yaml.safe_load(Path(args.org).read_text()) if args.org else None
    report = validate_pack(args.pack, org=org)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"aos validate {report.pack} v{report.version}  digest {report.digest[:12]}")
        print("  " + "  ".join(f"{k}={v}" for k, v in report.counts.items()))
        for issue in report.issues:
            print("  " + str(issue))
        verdict = "OK" if report.ok else "FAILED"
        print(f"{verdict}: {len(report.errors)} errors, {len(report.warnings)} warnings")
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aos", description="AOS pack tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check schemas and every cross-reference in a pack")
    v.add_argument("pack", help="path to the pack folder")
    v.add_argument("--org", help="organization YAML to check owners and placements against")
    v.add_argument("--json", action="store_true", help="print the report as JSON")
    v.set_defaults(func=_validate)
    args = parser.parse_args(argv)
    return args.func(args)


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
