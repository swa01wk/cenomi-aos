#!/usr/bin/env bash
# Sync the pack baked into the running API container into Postgres (local Docker stack).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/deploy"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
docker compose --env-file "$ENV_FILE" exec -T api python -c "
import asyncio
from psycopg import AsyncConnection
from aos.kernel.settings import Settings
from aos.kernel.org import load_org
from aos.kernel import registry_store
from aos.kernel.seats import insert_seats_for_published_pack

async def main() -> None:
    s = Settings.from_env()
    org = load_org(s.org_file)
    org_id = org.organization.id
    name = '${PACK_NAME:-procurement_demo}'
    async with await AsyncConnection.connect(s.database_url) as conn:
        r = await registry_store.sync_pack(
            conn, org=org, packs_dir=s.packs_dir, name=name, actor='sync-pack-docker'
        )
        print(f'sync {r.pack} v{r.version} -> {r.pack_version_id} ({r.status}, created={r.created})')
        await conn.execute(
            \"update registry.pack_versions set status = 'published', published_at = coalesce(published_at, now()) where id = %s\",
            (r.pack_version_id,),
        )
        await insert_seats_for_published_pack(
            conn, org=org, org_id=org_id, pack_version_id=r.pack_version_id
        )
        await conn.execute(
            \"update registry.seats set state = 'ACTIVE', configured_by = 'platform_admin', activated_by = 'head_of_procurement'\"
            \" where org_id = %s and name = 'seat_workspace_coordinator' and state in ('DRAFT', 'CONFIGURED', 'TESTING')\",
            (org_id,),
        )
        cur = await conn.execute(
            'update registry.seats set pack_version_id = %s where org_id = %s returning name',
            (r.pack_version_id, org_id),
        )
        seats = [row[0] for row in await cur.fetchall()]
        print('seats now on v%s: %s' % (r.version, ', '.join(seats) or 'none'))
        await conn.commit()

asyncio.run(main())
"
