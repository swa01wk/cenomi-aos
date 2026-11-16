#!/usr/bin/env bash
# Clean slate + full RFP client demo (Evaluation, all three personas, chat history).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/docker-compose.yml")
API="${E2E_API_URL:-http://localhost:8000}"

echo "Resetting workspace…"
bash "$ROOT/scripts/reset-demo.sh"

echo "Waiting for API…"
for _ in $(seq 1 30); do
  curl -sf "$API/api/healthz" >/dev/null && break
  sleep 1
done

echo "Bootstrapping full RFP demo…"
TOKEN="$(curl -sf -X POST "$API/api/auth/session" -H 'Content-Type: application/json' -d '{"person_id":"platform_admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
RESP="$(curl -sf -X POST "$API/api/demo/rfp/bootstrap" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"RFP-0001","replace":true}')"
echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("Ready:", d["instance_id"], "state=", d["state"])'
echo ""
echo "Open http://localhost:8080/workspace/jobs/RFP-0001 as Noura, Samir (cdo), or Rami."
echo "Backup when happy: make demo-backup INSTANCE=RFP-0001"
