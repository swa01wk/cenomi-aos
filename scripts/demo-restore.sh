#!/usr/bin/env bash
# Restore a demo job backup. Usage: make demo-restore FILE=demo/backups/RFP-0001-....json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${FILE:?set FILE= path to export JSON}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
API="${E2E_API_URL:-http://localhost:8000}"
TOKEN="$(curl -sf -X POST "$API/api/auth/session" -H 'Content-Type: application/json' -d '{"person_id":"platform_admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
curl -sf -X POST "$API/api/demo/instances/import" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @"$FILE" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("Restored", d["instance_id"])'
