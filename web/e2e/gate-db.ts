import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

// The gate reads the job's execution events straight from the Compose stack's Postgres: no API serves them in M1,
// and the gate already needs that stack. Paths are relative to web/, where Playwright runs.
const ROOT = resolve(process.cwd(), "..");

function compose(): string[] {
  const env = resolve(ROOT, ".env");
  return [
    "compose",
    ...(existsSync(env) ? ["--env-file", env] : []),
    "-f",
    resolve(ROOT, "deploy/docker-compose.yml"),
  ];
}

/** Run one read-only query as the database owner; rows come back as arrays of strings. */
export function query(sql: string): string[][] {
  const out = execFileSync(
    "docker",
    [...compose(), "exec", "-T", "postgres", "psql", "-U", "aos_owner", "-d", "aos", "-At", "-F", "\t", "-c", sql],
    { encoding: "utf8" },
  );
  return out
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => line.split("\t"));
}

export type RunEvent = { attemptId: string; type: string; tool: string; argsSha: string };

/** Execution events of one job (run id = instance id), oldest first. */
export function runEvents(instanceId: string): RunEvent[] {
  if (!/^[A-Za-z0-9_-]+$/.test(instanceId)) throw new Error(`unexpected instance id ${instanceId}`);
  return query(
    "select coalesce(attempt_id, ''), event_type, coalesce(attributes->>'tool', ''), " +
      "coalesce(attributes->>'args_sha256', '') from evidence.execution_events " +
      `where run_id = '${instanceId}' order by occurred_at, aggregate_seq`,
  ).map(([attemptId, type, tool, argsSha]) => ({ attemptId, type, tool, argsSha }));
}
