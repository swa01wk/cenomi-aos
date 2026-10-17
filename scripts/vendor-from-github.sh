#!/usr/bin/env bash
# Fallback for sandboxes where PyPI is blocked but GitHub is reachable: fetch the pure-Python
# dependencies the M0 backend needs at pinned release tags into backend/.vendor (git-ignored).
# Normal machines don't need this: `make install` uses pip.
set -euo pipefail
cd "$(dirname "$0")/../backend"
SRC=.vendor-src; OUT=.vendor
mkdir -p "$SRC" "$OUT"

fetch() {  # repo tag
  local name; name=$(basename "$1")
  [ -d "$SRC/$name" ] || git -c advice.detachedHead=false clone -q --depth 1 ${2:+--branch "$2"} "https://github.com/$1" "$SRC/$name"
}

fetch fastapi/fastapi 0.143.1
fetch psycopg/psycopg 3.3.6
fetch fastapi/annotated-doc ""

rm -rf "$OUT"/{fastapi,psycopg,psycopg_pool,annotated_doc}
cp -r "$SRC/fastapi/fastapi" "$OUT/"
cp -r "$SRC/psycopg/psycopg/psycopg" "$OUT/"
cp -r "$SRC/psycopg/psycopg_pool/psycopg_pool" "$OUT/"
cp -r "$SRC/annotated-doc/src/annotated_doc" "$OUT/"
echo "vendored into backend/$OUT: $(ls "$OUT" | tr '\n' ' ')"
echo "needs from the system: starlette, pydantic, PyYAML, PyJWT, mcp, uvicorn, libpq5"
