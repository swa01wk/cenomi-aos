#!/usr/bin/env bash
# Post-bootstrap checks for RFP-0001 client demo (spec stage, rubrics, eval).
set -euo pipefail
API="${E2E_API_URL:-http://localhost:8000}"
INSTANCE="${1:-RFP-0001}"

TOKEN="$(curl -sf -X POST "$API/api/auth/session" -H 'Content-Type: application/json' -d '{"person_id":"noura"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"

SNAP="$(curl -sf "$API/api/instances/$INSTANCE" -H "Authorization: Bearer $TOKEN")" || {
  echo "GET /api/instances/$INSTANCE failed"
  exit 22
}

python3 - "$SNAP" <<'PY'
import json, sys
snap = json.loads(sys.argv[1])
required_types = [
    "rfp_procurement_validation",
    "rfp_template_compliance",
    "scoring_method_agreement",
    "rfp_upload_manifest",
    "master_rfp",
    "technical_criterion_scores",
    "commercial_criterion_scores",
    "eval_scoring_policy",
    "rfp_eval_technical",
    "rfp_eval_commercial",
    "rfp_evaluation",
    "rfp_module_matrix",
    "rfp_module_scores",
]
arts = {a["artifact_type"] for a in snap.get("artifacts", [])}
missing = [t for t in required_types if t not in arts]
ok = [t for t in required_types if t in arts]
print(f"Instance {snap.get('instance_id')} state={snap.get('state')} pack={snap.get('pack_version', 'unknown')}")
print(f"OK ({len(ok)}): {', '.join(ok)}")
if missing:
    print(f"MISSING: {', '.join(missing)}")
    sys.exit(1)
turns = snap.get("turns") or []
needles = ["back to Faisal", "70/30", "Scoring agreement", "question_lane", "Send BAFO"]
for n in needles:
    found = any(n.lower() in json.dumps(t).lower() for t in turns)
    print(f"chat needle {'OK' if found else 'MISS'!s}: {n}")
    if not found:
        sys.exit(2)
# Rubric row count via first technical_criterion_scores artifact
tid = next(a["artifact_id"] for a in snap["artifacts"] if a["artifact_type"] == "technical_criterion_scores")
print(f"technical_criterion_scores id={tid}")
PY

VID="$(echo "$SNAP" | python3 -c 'import sys,json; s=json.load(sys.stdin); print(next(a["latest_version"] for a in s["artifacts"] if a["artifact_type"]=="technical_criterion_scores"))')"
AID="$(echo "$SNAP" | python3 -c 'import sys,json; s=json.load(sys.stdin); print(next(a["artifact_id"] for a in s["artifacts"] if a["artifact_type"]=="technical_criterion_scores"))')"
RUB="$(curl -sf "$API/api/artifacts/$AID/versions/$VID" -H "Authorization: Bearer $TOKEN")"
echo "$RUB" | python3 -c 'import sys,json; c=json.load(sys.stdin)["content"]; rows=c.get("rows") or []; print(f"Technical rubric rows: {len(rows)}"); assert len(rows)>=15, rows'
SCORE="$(echo "$SNAP" | python3 -c 'import sys,json; s=json.load(sys.stdin); print(next(a["artifact_id"] for a in s["artifacts"] if a["artifact_type"]=="scoring_method_agreement"))')"
SCOREV="$(curl -sf "$API/api/artifacts/$SCORE/versions/1" -H "Authorization: Bearer $TOKEN")"
echo "$SCOREV" | python3 -c 'import sys,json; c=json.load(sys.stdin)["content"]; assert c.get("agreed_technical_weight")==0.7; assert c.get("agreed_commercial_weight")==0.3; print("Scoring agreement: 70/30 QCBS OK")'
echo "All RFP-0001 demo checks passed."
