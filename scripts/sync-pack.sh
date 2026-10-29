#!/usr/bin/env bash
# Sync the on-disk demo pack into Postgres, publish that version, and point active seats at it.
# Use after bumping metadata.version in pack.yaml (common in local dev).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
export PYTHONPATH="${ROOT}/backend/src:${ROOT}/backend/.vendor"
PACK_NAME="${PACK_NAME:-procurement_demo}"
python <<PY
import asyncio
from aos.kernel.settings import Settings
from aos.kernel.org import load_org
from aos.kernel import registry_store
from aos.kernel.seats import insert_seats_for_published_pack
from psycopg_pool import AsyncConnectionPool

async def main() -> None:
    s = Settings.from_env()
    org = load_org(s.org_file)
    org_id = org.organization.id
    pool = AsyncConnectionPool(s.database_url, open=False)
    await pool.open()
    async with pool.connection() as conn:
        r = await registry_store.sync_pack(
            conn, org=org, packs_dir=s.packs_dir, name="${PACK_NAME}", actor="sync-pack"
        )
        print(f"sync {r.pack} v{r.version} -> {r.pack_version_id} ({r.status}, created={r.created})")
        await conn.execute(
            "update registry.pack_versions set status = 'published',"
            " published_at = coalesce(published_at, now()) where id = %s",
            (r.pack_version_id,),
        )
        await insert_seats_for_published_pack(
            conn, org=org, org_id=org_id, pack_version_id=r.pack_version_id
        )
        await conn.execute(
            "update registry.seats set state = 'ACTIVE', configured_by = 'platform_admin',"
            " activated_by = 'head_of_procurement'"
            " where org_id = %s and name = 'seat_workspace_coordinator'"
            " and state in ('DRAFT', 'CONFIGURED', 'TESTING')",
            (org_id,),
        )
        cur = await conn.execute(
            "update registry.seats set pack_version_id = %s where org_id = %s returning name",
            (r.pack_version_id, org_id),
        )
        seats = [row[0] for row in await cur.fetchall()]
        print(f"seats now on v{r.version}: {', '.join(seats) or '(none)'}")
        await conn.commit()
    await pool.close()

asyncio.run(main())
PY
