#!/usr/bin/env bash
# Wipe all jobs, chat, artifacts, and connector mail — keep org, packs, and ERP catalog.
# Usage: from repo root, with `make up` running:  make reset-demo
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/docker-compose.yml")

echo "Resetting demo workspace (jobs, chat, mail, evidence)…"
"${COMPOSE[@]}" exec -T postgres psql -U aos_owner -d aos -v ON_ERROR_STOP=1 <<'SQL'
truncate table
  work.inbound_messages,
  work.instance_shared_attachments,
  work.pending_items,
  work.artifact_versions,
  work.artifacts,
  work.attempts,
  work.turns,
  work.tasks,
  work.regions,
  work.timers,
  work.instance_transitions,
  work.participants,
  work.notifications,
  work.instances,
  evidence.execution_events,
  evidence.stream_heads,
  evidence.tool_payloads,
  evidence.outbox,
  gov.decision_records,
  gov.budget_ledger
restart identity cascade;
alter sequence work.instance_number restart with 1;
delete from work.demo_clock;
SQL

echo "Clearing mock mail (RFQs and vendor replies)…"
"${COMPOSE[@]}" exec -T mock-mail python - <<'PY'
from aos.connectors.base import Store
import os

db = os.environ.get("MOCK_MAIL_DB", "/data/mock_mail.sqlite")
store = Store(db, "")
store.x("delete from notification")
store.x("delete from message")
print("mock_mail cleared")
PY

echo "Re-seeding organization from seed/org.yaml…"
"${COMPOSE[@]}" exec -T api python - <<'PY'
import asyncio
from aos.kernel.org import load_org, seed_sql
from aos.kernel.settings import Settings
import psycopg

async def main() -> None:
    s = Settings.from_env()
    org = load_org(s.org_file)
    async with await psycopg.AsyncConnection.connect(s.database_url, autocommit=True) as conn:
        await conn.execute(seed_sql(org))
    print("org seed applied")

asyncio.run(main())
PY

echo "Syncing procurement pack…"
bash "$ROOT/scripts/sync-pack-docker.sh" || true

echo "Done. New jobs start at QQ-0001 / RFP-0001. Sign in at http://localhost:8080"
