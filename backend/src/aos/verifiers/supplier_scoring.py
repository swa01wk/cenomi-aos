"""Quick Quote supplier ranking rubric (shareable fields on supplier_list rows)."""

from __future__ import annotations

from typing import Any


def score_breakdown(past_pos: Any, on_time_pct: Any) -> dict[str, int]:
    """Deterministic score used by supplier_lookup and sourcing_assist explanations."""
    points_asl = 20
    pp = max(0, int(past_pos or 0))
    points_history = min(pp * 5, 50)
    if pp == 0 or on_time_pct is None:
        points_delivery = 0
    else:
        points_delivery = round(float(on_time_pct) * 0.3)
    total = points_asl + points_history + points_delivery
    return {
        "points_asl": points_asl,
        "points_history": points_history,
        "points_delivery": points_delivery,
        "score": total,
    }


def heal_supplier_list_content(content: dict[str, Any]) -> dict[str, Any]:
    """Recompute rubric fields when the worker saved score 0 but history columns are present."""
    rows = content.get("rows")
    if not isinstance(rows, list):
        return content
    healed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            healed.append(row)
            continue
        patch = score_breakdown(row.get("past_pos"), row.get("on_time_pct"))
        new_row = {**row, **patch}
        healed.append(new_row)
    healed.sort(key=lambda r: (-float(r.get("score") or 0), str(r.get("supplier") or "")))
    for i, row in enumerate(healed, start=1):
        if isinstance(row, dict):
            row["rank"] = i
    return {**content, "rows": healed}


def check_row_scoring(row: dict[str, Any], *, row_label: str) -> list[str]:
    findings: list[str] = []
    score = row.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return findings
    expected = score_breakdown(row.get("past_pos"), row.get("on_time_pct"))
    if abs(float(score) - expected["score"]) > 0.01:
        findings.append(
            f"{row_label}: score {score} does not match the rubric total {expected['score']} "
            f"(20 on the approved list + up to 50 for past orders + up to 30 for on-time delivery)."
        )
    for key in ("points_asl", "points_history", "points_delivery"):
        if key not in row:
            continue
        val = row.get(key)
        if not isinstance(val, int) or isinstance(val, bool):
            findings.append(f"{row_label}: {key} must be a whole number.")
        elif val != expected[key]:
            findings.append(f"{row_label}: {key} should be {expected[key]}.")
    return findings
