#!/usr/bin/env bash
# Sync the pack baked into the running API container into Postgres, publish, and repoint seats.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/deploy"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
docker compose --env-file "$ENV_FILE" exec -T api python -c "
import asyncio
from psycopg import AsyncConnection
from aos.kernel.settings import Settings
from aos.kernel.org import load_org
from aos.kernel.pack_publish import ensure_all_packs_published

async def main() -> None:
    s = Settings.from_env()
    org = load_org(s.org_file)
    async with await AsyncConnection.connect(s.database_url) as conn:
        async with conn.transaction():
            results = await ensure_all_packs_published(
                conn, org=org, packs_dir=s.packs_dir, actor='sync-pack-docker'
            )
            for r in results:
                print(f'sync {r.pack} v{r.version} -> {r.pack_version_id} ({r.status}, created={r.created})')

asyncio.run(main())
"
