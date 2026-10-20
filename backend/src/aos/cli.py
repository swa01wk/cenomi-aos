"""The ``aos`` command line. M0 ships ``validate``; simulate, test, diff and publish arrive in later milestones."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

import asyncio

from psycopg_pool import AsyncConnectionPool

from .kernel.auth import issue_worker_token
from .kernel.org import load_org, seed_sql
from .kernel.simulate import run_simulation_cli_rolled_back
from .kernel.settings import Settings
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


def _simulate(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    org = load_org(settings.org_file)
    org_id = org.organization.id
    pack_dir = Path(args.pack).resolve()
    script = args.script or "dry_run_script"

    async def _run() -> dict:
        pool = AsyncConnectionPool(settings.database_url, open=False)
        await pool.open()
        try:
            async with pool.connection() as conn:
                await conn.execute(seed_sql(org))
                await conn.commit()
            return await run_simulation_cli_rolled_back(
                pool,
                org,
                org_id=org_id,
                pack_dir=pack_dir,
                workflow_name=args.workflow,
                script_name=script,
            )
        finally:
            await pool.close()

    report = asyncio.run(_run())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"simulate {report['workflow']} reached {report['reached']}"
            f"  tasks={report['tasks_created']}  dead_ends={len(report['dead_ends'])}"
        )
    return 0 if report.get("reached") == "closed" else 1


def _worker_token(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    org = load_org(settings.org_file)
    token = issue_worker_token(org.organization.id, args.worker_id, settings.session_secret)
    print(token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aos", description="AOS pack tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check schemas and every cross-reference in a pack")
    v.add_argument("pack", help="path to the pack folder")
    v.add_argument("--org", help="organization YAML to check owners and placements against")
    v.add_argument("--json", action="store_true", help="print the report as JSON")
    v.set_defaults(func=_validate)
    sim = sub.add_parser("simulate", help="run a scripted workflow simulation (rolled back, never persists)")
    sim.add_argument("pack", help="path to the pack folder")
    sim.add_argument("--workflow", required=True, help="workflow name")
    sim.add_argument("--script", help="eval script name (default dry_run_script)")
    sim.add_argument("--json", action="store_true", help="print SimulationReport as JSON")
    sim.set_defaults(func=_simulate)
    wt = sub.add_parser("worker-token", help="mint a worker service JWT (aud aos-worker) for development")
    wt.add_argument("--worker-id", required=True, help="worker process id (token sub claim)")
    wt.set_defaults(func=_worker_token)
    args = parser.parse_args(argv)
    return args.func(args)


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
