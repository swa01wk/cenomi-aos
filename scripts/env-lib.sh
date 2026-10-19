# Shared helpers for scripts that read and edit .env. Source it; expects ENV_FILE.

# Last value of KEY in .env (empty when unset).
env_value() { grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true; }

# Replace KEY=... in .env, or append it. Portable (no sed -i differences between macOS and Linux).
set_value() {
  local tmp
  tmp=$(mktemp)
  awk -v k="$1" -v v="$2" 'BEGIN { done = 0 }
    index($0, k "=") == 1 { print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" >"$tmp"
  mv "$tmp" "$ENV_FILE"
}
