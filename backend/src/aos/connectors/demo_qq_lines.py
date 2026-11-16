"""Line-item Quick Quote comparison (demo — e.g. iPhone RFQ)."""

from __future__ import annotations

import statistics
from typing import Any

QQ_LINE_ITEMS: tuple[tuple[str, str], ...] = (
    ("LINE-01", "Device unit (iPhone Pro Max 512 GB)"),
    ("LINE-02", "AppleCare / extended warranty"),
    ("LINE-03", "Delivery to site"),
    ("LINE-04", "MDM setup and enrollment"),
)

# supplier key -> per-line SAR (single-unit RFQ; scaled by quantity in heal)
_DEMO_LINE_AMOUNTS: dict[str, dict[str, float]] = {
    "SUP-11632": {
        "LINE-01": 5_250.0,
        "LINE-02": 420.0,
        "LINE-03": 180.0,
        "LINE-04": 120.0,
    },
    "SUP-10482": {
        "LINE-01": 5_380.0,
        "LINE-02": 460.0,
        "LINE-03": 210.0,
        "LINE-04": 140.0,
    },
    "SUP-11615": {
        "LINE-01": 5_120.0,
        "LINE-02": 399.0,
        "LINE-03": 195.0,
        "LINE-04": 136.0,
    },
}

_DEMO_SUPPLIER_NAMES: dict[str, str] = {
    "SUP-11632": "Webknot Technologies",
    "SUP-10482": "Najd Supplies",
    "SUP-11615": "SUP-11615",
}


def _display_name(supplier_key: str) -> str:
    if supplier_key in _DEMO_SUPPLIER_NAMES:
        name = _DEMO_SUPPLIER_NAMES[supplier_key]
        if name.startswith("SUP-"):
            return supplier_key
        return name
    return supplier_key


def _normalize_supplier_key(label: str) -> str:
    t = label.strip()
    if t.startswith("SUP-"):
        return t
    for sid, name in _DEMO_SUPPLIER_NAMES.items():
        if name == t:
            return sid
    if "webknot" in t.lower():
        return "SUP-11632"
    if "najd" in t.lower():
        return "SUP-10482"
    return t


def resolve_three_suppliers(existing: list[str]) -> tuple[str, str, str]:
    """Keep awarded/quoted vendor first; fill with demo peers."""
    ordered: list[str] = []
    for s in existing:
        key = _normalize_supplier_key(s)
        if key and key not in ordered:
            ordered.append(key)
    for sid in ("SUP-11615", "SUP-11632", "SUP-10482"):
        if sid not in ordered:
            ordered.append(sid)
        if len(ordered) >= 3:
            break
    while len(ordered) < 3:
        ordered.append(f"SUP-DEMO-{len(ordered)+1}")
    return ordered[0], ordered[1], ordered[2]


def _amounts_for(supplier_key: str, quantity: int) -> dict[str, float]:
    base = dict(_DEMO_LINE_AMOUNTS.get(supplier_key) or _DEMO_LINE_AMOUNTS["SUP-10482"])
    q = max(1, quantity)
    return {lid: round(v * q, 2) for lid, v in base.items()}


def pricing_lines_for(supplier_key: str, quantity: int) -> list[dict[str, Any]]:
    names = {lid: label for lid, label in QQ_LINE_ITEMS}
    amounts = _amounts_for(supplier_key, quantity)
    return [{"line_id": lid, "name": names[lid], "amount": amounts[lid]} for lid, _ in QQ_LINE_ITEMS]


def quote_total(supplier_key: str, quantity: int) -> float:
    return sum(float(line["amount"]) for line in pricing_lines_for(supplier_key, quantity))


def _fair_benchmarks(quantity: int) -> dict[str, float]:
    by_line: dict[str, list[float]] = {lid: [] for lid, _ in QQ_LINE_ITEMS}
    for sid in _DEMO_LINE_AMOUNTS:
        for lid, val in _amounts_for(sid, quantity).items():
            by_line[lid].append(val)
    return {lid: round(statistics.median(vals), 2) for lid, vals in by_line.items() if vals}


def _variance_pct(quoted: float, fair: float) -> float:
    if fair <= 0:
        return 0.0
    return round((quoted - fair) / fair * 100, 1)


def build_line_matrix_rows(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> list[dict[str, Any]]:
    fair = _fair_benchmarks(quantity)
    names = {lid: label for lid, label in QQ_LINE_ITEMS}
    labels = [_display_name(k) for k in supplier_keys]
    rows: list[dict[str, Any]] = []
    for lid, label in QQ_LINE_ITEMS:
        amounts = [_amounts_for(k, quantity)[lid] for k in supplier_keys]
        fair_amt = fair[lid]
        high_idx = max(range(3), key=lambda i: amounts[i])
        high_label = labels[high_idx]
        vpct = _variance_pct(amounts[high_idx], fair_amt)
        rows.append(
            {
                "line_id": lid,
                "line_name": names[lid],
                "fair_benchmark": fair_amt,
                "supplier_a": labels[0],
                "supplier_a_sar": amounts[0],
                "supplier_b": labels[1],
                "supplier_b_sar": amounts[1],
                "supplier_c": labels[2],
                "supplier_c_sar": amounts[2],
                "high_supplier": high_label,
                "vs_fair_pct": vpct,
                "negotiation_note": (
                    f"{high_label} is {vpct:+.1f}% vs fair on {label}; ask why their {label} is "
                    f"SAR {amounts[high_idx]:,.0f} when peers cluster near SAR {fair_amt:,.0f}."
                ),
            }
        )
    return rows


def build_line_score_rows(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> list[dict[str, Any]]:
    fair = _fair_benchmarks(quantity)
    names = {lid: label for lid, label in QQ_LINE_ITEMS}
    rows: list[dict[str, Any]] = []
    for sid in supplier_keys:
        supplier = _display_name(sid)
        for line in pricing_lines_for(sid, quantity):
            lid = str(line["line_id"])
            quoted = float(line["amount"])
            fair_amt = fair.get(lid, quoted)
            vpct = _variance_pct(quoted, fair_amt)
            score = round(max(0.0, min(100.0, 100.0 - abs(vpct) * 2.5)), 1)
            rows.append(
                {
                    "line_supplier_id": f"{lid}:{sid}",
                    "line_id": lid,
                    "line_name": names.get(lid, line.get("name", lid)),
                    "supplier": supplier,
                    "quoted_amount": quoted,
                    "fair_benchmark": fair_amt,
                    "variance_pct": vpct,
                    "line_score": score,
                }
            )
    return rows


def build_comparison_rows(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> list[dict[str, Any]]:
    ranked: list[tuple[str, float, int]] = []
    for sid in supplier_keys:
        total = quote_total(sid, quantity)
        ranked.append((sid, total, 5 if sid == supplier_keys[0] else 7))
    ranked.sort(key=lambda x: (x[1], x[2]))
    rows: list[dict[str, Any]] = []
    for i, (sid, total, lead) in enumerate(ranked, start=1):
        unit = total / max(1, quantity)
        rows.append(
            {
                "rank": i,
                "supplier": _display_name(sid),
                "unit_price": unit,
                "total": total,
                "lead_time_days": lead,
                "warranty_months": 12,
                "score": round(100.0 - (i - 1) * 4.5, 1),
            }
        )
    return rows


from .demo_eval_rubrics import (
    OVERALL_COMMERCIAL_WEIGHT,
    OVERALL_TECHNICAL_WEIGHT,
    commercial_envelope_score,
    qq_rubric_bundle,
    scoring_policy_content,
    weighted_combined,
)

COMMERCIAL_WEIGHT = OVERALL_COMMERCIAL_WEIGHT
TECHNICAL_WEIGHT = OVERALL_TECHNICAL_WEIGHT

def build_qq_eval_artifacts(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    names = {sid: _display_name(sid) for sid in supplier_keys}
    totals = {sid: float(quote_total(sid, quantity)) for sid in supplier_keys}
    tech_rows, comm_rows, _, tech_scores = qq_rubric_bundle(
        list(supplier_keys), names, totals
    )
    comm_scores = {sid: commercial_envelope_score(comm_rows, sid) for sid in supplier_keys}
    ranked = sorted(
        supplier_keys,
        key=lambda sid: weighted_combined(comm_scores.get(sid, 0), tech_scores.get(sid, 0)),
        reverse=True,
    )
    commercial_rows: list[dict[str, Any]] = []
    technical_rows: list[dict[str, Any]] = []
    weighted_rows: list[dict[str, Any]] = []
    for rank, sid in enumerate(ranked, start=1):
        name = names[sid]
        total = totals[sid]
        c = comm_scores.get(sid, 85.0)
        t = tech_scores.get(sid, 85.0)
        w = weighted_combined(c, t)
        commercial_rows.append(
            {
                "rank": rank,
                "supplier": name,
                "total": total,
                "lead_time_days": 5 if sid == supplier_keys[0] else 7,
                "commercial_score": c,
                "notes": "Commercial envelope from line price (QCBS) plus lead time and warranty criteria.",
            }
        )
        technical_rows.append(
            {
                "rank": rank,
                "supplier": name,
                "supplier_id": sid,
                "technical_score": t,
                "notes": (
                    "Technical score from Quick Quote criterion rubric (0–5). "
                    "Open **Scoring rubric and calculation** for details."
                ),
            }
        )
        weighted_rows.append(
            {
                "rank": rank,
                "supplier": name,
                "supplier_id": sid,
                "total": total,
                "lead_time_days": 5 if sid == supplier_keys[0] else 7,
                "commercial_score": c,
                "technical_score": t,
                "weighted_score": w,
                "commercial_weight": COMMERCIAL_WEIGHT,
                "technical_weight": TECHNICAL_WEIGHT,
            }
        )
    return commercial_rows, technical_rows, weighted_rows


def build_qq_rubric_artifacts(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    names = {sid: _display_name(sid) for sid in supplier_keys}
    totals = {sid: float(quote_total(sid, quantity)) for sid in supplier_keys}
    tech_rows, comm_rows, _, _ = qq_rubric_bundle(list(supplier_keys), names, totals)
    policy = scoring_policy_content(envelope_label="Quick Quote")
    return tech_rows, comm_rows, policy


def format_qq_eval_chat_block(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> str:
    _, _, weighted = build_qq_eval_artifacts(supplier_keys, quantity=quantity)
    lines = [
        "**Commercial eval**, **Technical eval**, and **Weighted eval** (30% / 70% per PRD) for all three quotes:",
        "",
    ]
    for row in weighted:
        lines.append(
            f"- **{row['supplier']}** — commercial {row['commercial_score']}, technical "
            f"{row['technical_score']}, weighted **{row['weighted_score']}**"
        )
    lines.append("")
    lines.append(
        "Commercial clarification questions go to **Noura** (procurement). "
        "Technical questions (spec, MDM, warranty) go to the **category manager**."
    )
    return "\n".join(lines)


def format_qq_line_comparison_chat_block(
    supplier_keys: tuple[str, str, str],
    *,
    quantity: int = 1,
) -> str:
    rows = build_line_matrix_rows(supplier_keys, quantity=quantity)
    lines = [
        "**Line-item comparison** across **three** bidders "
        f"({', '.join(_display_name(k) for k in supplier_keys)}). "
        "Fair benchmark = median quote per line:",
        "",
    ]
    for row in rows[:4]:
        lines.append(
            f"**{row['line_id']}** {row['line_name']}\n"
            f"- Fair: SAR {float(row['fair_benchmark']):,.0f}\n"
            f"- {row['supplier_a']}: SAR {float(row['supplier_a_sar']):,.0f} · "
            f"{row['supplier_b']}: SAR {float(row['supplier_b_sar']):,.0f} · "
            f"{row['supplier_c']}: SAR {float(row['supplier_c_sar']):,.0f}\n"
            f"- Outlier: **{row['high_supplier']}** ({float(row['vs_fair_pct']):+.1f}% vs fair)"
        )
        lines.append("")
    lines.append(
        "Open **Line comparison** and **Line scores** in the work panel (Documents) beside **Comparison**."
    )
    return "\n".join(lines)
