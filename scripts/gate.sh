#!/usr/bin/env bash
# M1 exit gate on the real model (`make gate`, `make gate RUNS=3`).
#
# Switches the worker to the real model, resets the stack, then runs the Playwright project `gate`: stops 1–3
# publish the pack and activate the Seat, and e2e/m1-gate-real-model.spec.ts has Faisal chat and checks the brief and
# the agent's conduct. With RUNS > 1 the chat runs again on the same stack (a new job each time) and the report
# gives each check's pass rate. Each run's results and screenshots go to web/gate-results/run-<n>/.
set -uo pipefail
cd "$(dirname "$0")/.."

runs=${1:-1}
[[ "$runs" =~ ^[1-9][0-9]*$ ]] || { echo "RUNS must be a positive number" >&2; exit 2; }

bash scripts/dev-model.sh real || exit 1
make --no-print-directory down V=1 || exit 1
make --no-print-directory up || exit 1

rm -rf web/gate-results
mkdir -p web/gate-results
for ((i = 1; i <= runs; i++)); do
  echo ""
  echo "== M1 gate run $i of $runs"
  deps=()
  [ "$i" -gt 1 ] && deps=(--no-deps)  # stops 1–3 publish once; later runs reuse the active Seat
  (cd web && E2E_GATE=1 PLAYWRIGHT_JSON_OUTPUT_FILE="gate-results/run-$i.json" \
    npx playwright test --project=gate ${deps[@]+"${deps[@]}"} --output="gate-results/run-$i" --reporter=list,json)
  status=$?
  if [ "$i" -eq 1 ] && [ "$status" -ne 0 ] && ! python3 scripts/gate-report.py --chat-ran web/gate-results/run-1.json; then
    echo "Stops 1–3 didn't complete; not running the chat again." >&2
    break
  fi
done

echo ""
python3 scripts/gate-report.py web/gate-results/run-*.json
result=$?
if [ "$result" -ne 0 ]; then
  echo ""
  echo "Worker log and events for the last run:"
  make --no-print-directory diag
fi
echo ""
echo "Screenshots and results: web/gate-results/. The stack is still on the real model; back to scripted:"
echo "make model-fake && make up"
exit "$result"
