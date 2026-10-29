#!/usr/bin/env bash
# Mint a development worker token and write it to .env, so `make up` can start the worker.
#
#   scripts/dev-worker-token.sh               always mint a new token
#   scripts/dev-worker-token.sh --if-missing  only when .env has no token, or it expires within the hour (`make up`)
#
# Assist fake replies use per-skill scripts (e.g. workspace_coordinate.happy.yaml) unless AOS_FAKE_SCRIPT is set.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"

# shellcheck source=env-lib.sh
source scripts/env-lib.sh
is_jwt() { [[ "$1" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; }

# Worker tokens expire (8 h). True when the token's exp is more than an hour away; when python3 isn't there to
# read it, assume it's fine (`make worker-token` forces a new one).
token_fresh() {
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - "$1" <<'PY'
import base64, json, sys, time
try:
    part = sys.argv[1].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    sys.exit(0 if claims.get("exp", 0) - time.time() > 3600 else 1)
except Exception:
    sys.exit(1)
PY
}

current=$(env_value AOS_WORKER_TOKEN)
if [ "${1:-}" = "--if-missing" ] && is_jwt "$current" && token_fresh "$current"; then
  exit 0
fi

# The token is signed with the API's session secret, so mint it with the same one the stack will use.
# Compose is run without --env-file so a broken AOS_WORKER_TOKEN line in .env can't get in the way.
secret=$(env_value AOS_SESSION_SECRET)
compose=(docker compose -f deploy/docker-compose.yml)
export AOS_WORKER_TOKEN=unused
[ -n "$secret" ] && export AOS_SESSION_SECRET="$secret"

echo "Minting a worker token (builds the api image if needed)..."
"${compose[@]}" build api >/dev/null
token=$("${compose[@]}" run --rm --no-deps -T api aos worker-token --worker-id dev-worker-1 2>/dev/null \
  | tail -n 1 | tr -d '\r')
if ! is_jwt "$token"; then
  echo "Could not mint a worker token; run: docker compose -f deploy/docker-compose.yml run --rm --no-deps -T api aos worker-token --worker-id dev-worker-1" >&2
  exit 1
fi

set_value AOS_WORKER_TOKEN "$token"
echo "Wrote AOS_WORKER_TOKEN to $ENV_FILE"
