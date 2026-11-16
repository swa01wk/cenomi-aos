#!/usr/bin/env bash
# Sync the on-disk demo pack into Postgres, publish that version, and point active seats at it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
export PYTHONPATH="${ROOT}/backend/src:${ROOT}/backend/.vendor"
python <<'PY'
import asyncio
from aos.kernel.settings import Settings
from aos.kernel.org import load_org
from aos.kernel.pack_publish import ensure_all_packs_published
from psycopg_pool import AsyncConnectionPool

async def main() -> None:
    s = Settings.from_env()
    org = load_org(s.org_file)
    pool = AsyncConnectionPool(s.database_url, open=False)
    await pool.open()
    async with pool.connection() as conn:
        async with conn.transaction():
            results = await ensure_all_packs_published(
                conn, org=org, packs_dir=s.packs_dir, actor="sync-pack"
            )
            for r in results:
                print(f"sync {r.pack} v{r.version} -> {r.pack_version_id} ({r.status}, created={r.created})")
    await pool.close()

asyncio.run(main())
PY
