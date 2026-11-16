#!/usr/bin/env bash
# Export a job snapshot for demo restore. Usage: make demo-backup INSTANCE=RFP-0001
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE="${INSTANCE:?set INSTANCE= e.g. RFP-0001}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
API="${E2E_API_URL:-http://localhost:8000}"
OUT_DIR="$ROOT/demo/backups"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/${INSTANCE}-${STAMP}.json"
TOKEN="$(curl -sf -X POST "$API/api/auth/session" -H 'Content-Type: application/json' -d '{"person_id":"platform_admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
curl -sf -H "Authorization: Bearer $TOKEN" "$API/api/demo/instances/${INSTANCE}/export" -o "$OUT"
echo "Wrote $OUT"
echo "Restore: make demo-restore FILE=$OUT"
