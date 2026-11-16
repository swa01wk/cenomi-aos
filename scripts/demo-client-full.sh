#!/usr/bin/env bash
# Reset + seed both client demos: web RFP (RFP-0001) and iPhone Quick Quote (QQ-0001).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
API="${E2E_API_URL:-http://localhost:8000}"

echo "Resetting workspace…"
bash "$ROOT/scripts/reset-demo.sh"

echo "Waiting for API…"
for _ in $(seq 1 30); do
  curl -sf "$API/api/healthz" >/dev/null && break
  sleep 1
done

TOKEN="$(curl -sf -X POST "$API/api/auth/session" -H 'Content-Type: application/json' -d '{"person_id":"platform_admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"

echo "Bootstrapping RFP (web redesign)…"
curl -sf -X POST "$API/api/demo/rfp/bootstrap" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"RFP-0001","replace":true}' | python3 -m json.tool

echo "Bootstrapping Quick Quote (iPhone)…"
curl -sf -X POST "$API/api/demo/qq/bootstrap" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"QQ-0001","replace":true}' | python3 -m json.tool

# Optional second QQ id used in live demos
curl -sf -X POST "$API/api/demo/qq/bootstrap" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"QQ-0013","replace":true}' 2>/dev/null | python3 -m json.tool || true

echo ""
echo "Open RFP:  http://localhost:8080/workspace/jobs/RFP-0001  (Noura / Rami / Samir)"
echo "Open iPhone: http://localhost:8080/workspace/jobs/QQ-0001 or QQ-0013 (Noura / Rami / Faisal)"
echo "Existing jobs also enrich on refresh when AOS_DEMO=1 (no reset required)."
