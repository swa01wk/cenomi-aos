"""PRD-aligned evaluation rubrics (QCBS): technical criteria 0–5 and commercial price formula."""

from __future__ import annotations

from typing import Any

# Section 6.3 / 8 — default envelope for formal RFP (web redesign and services).
TECHNICAL_CRITERIA_RFP: tuple[tuple[str, str, float], ...] = (
    ("T1", "Scope understanding and methodology", 25.0),
    ("T2", "Staffing and supervision", 20.0),
    ("T3", "Equipment and sustainability", 15.0),
    ("T4", "SLA, quality control and reporting", 25.0),
    ("T5", "Experience and references", 15.0),
)

# Quick Quote — device / goods (same 0–5 scale, category-specific labels).
TECHNICAL_CRITERIA_QQ: tuple[tuple[str, str, float], ...] = (
    ("Q1", "Specification match (model, storage, region)", 30.0),
    ("Q2", "MDM and enterprise readiness", 25.0),
    ("Q3", "Warranty and support", 20.0),
    ("Q4", "Delivery and logistics", 15.0),
    ("Q5", "Supplier track record", 10.0),
)

COMMERCIAL_CRITERIA_RFP: tuple[tuple[str, str, float], ...] = (
    ("C1", "Total evaluated price (normalized scope)", 70.0),
    ("C2", "Payment and contract terms", 15.0),
    ("C3", "Delivery and implementation timeline", 15.0),
)

COMMERCIAL_CRITERIA_QQ: tuple[tuple[str, str, float], ...] = (
    ("C1", "Line-item unit price (like-for-like)", 60.0),
    ("C2", "Lead time and availability", 25.0),
    ("C3", "Warranty and return policy", 15.0),
)

OVERALL_TECHNICAL_WEIGHT = 0.70
OVERALL_COMMERCIAL_WEIGHT = 0.30
MIN_TECHNICAL_SCORE = 70.0

def scoring_policy_content(*, envelope_label: str) -> dict[str, Any]:
    return {
        "technical_weight": OVERALL_TECHNICAL_WEIGHT,
        "commercial_weight": OVERALL_COMMERCIAL_WEIGHT,
        "min_technical_score": MIN_TECHNICAL_SCORE,
        "scale_0_5": "; ".join(SCORE_ANCHORS),
        "technical_formula": (
            "Technical score (0–100) = sum over criteria of (average evaluator score ÷ 5 × criterion weight %). "
            f"Criteria follow the {envelope_label} technical envelope in the rubric table below."
        ),
        "commercial_formula": (
            "Commercial score (0–100) = sum of weighted commercial criteria. "
            "Total evaluated price uses QCBS: (lowest qualified bid ÷ this bid) × 100 × price weight %. "
            f"Suppliers below {MIN_TECHNICAL_SCORE:.0f} technical are not qualified for commercial scoring."
        ),
        "combined_formula": (
            f"Weighted score = technical × {OVERALL_TECHNICAL_WEIGHT:.0%} + commercial × "
            f"{OVERALL_COMMERCIAL_WEIGHT:.0%}. Ties go to higher technical score."
        ),
    }


SCORE_ANCHORS = (
    "0 = not addressed",
    "1 = poor",
    "2 = partly meets, with concerns",
    "3 = meets",
    "4 = exceeds",
    "5 = clearly exceeds, with strong evidence",
)

# Demo 0–5 scores per supplier (RFP web redesign).
_RFP_DEMO_CRITERION_0_5: dict[str, dict[str, float]] = {
    "SUP-11836": {"T1": 4.4, "T2": 4.2, "T3": 4.0, "T4": 4.6, "T5": 4.5},
    "SUP-11564": {"T1": 4.6, "T2": 4.3, "T3": 4.2, "T4": 4.5, "T5": 4.6},
    "SUP-12448": {"T1": 4.0, "T2": 4.0, "T3": 3.8, "T4": 4.2, "T5": 4.0},
}

_QQ_DEMO_CRITERION_0_5: dict[str, dict[str, float]] = {
    "SUP-11615": {"Q1": 4.2, "Q2": 4.0, "Q3": 4.1, "Q4": 4.0, "Q5": 3.8},
    "SUP-11632": {"Q1": 4.5, "Q2": 4.4, "Q3": 4.2, "Q4": 3.8, "Q5": 4.0},
    "SUP-10482": {"Q1": 3.8, "Q2": 3.6, "Q3": 3.9, "Q4": 4.0, "Q5": 3.5},
}


def technical_score_from_criteria(
    scores_0_5: dict[str, float],
    criteria: tuple[tuple[str, str, float], ...],
) -> float:
    """Σ (score ÷ 5 × weight_pct) → score out of 100."""
    total = 0.0
    for cid, _, weight_pct in criteria:
        s = float(scores_0_5.get(cid, 3.0))
        total += (s / 5.0) * weight_pct
    return round(total, 1)


def commercial_price_score(
    supplier_total: float,
    lowest_total: float,
    *,
    qualified: bool,
) -> float:
    if not qualified:
        return 0.0
    if supplier_total <= 0 or lowest_total <= 0:
        return 0.0
    return round((lowest_total / supplier_total) * 100.0, 1)


def weighted_combined(commercial: float, technical: float) -> float:
    return round(
        commercial * OVERALL_COMMERCIAL_WEIGHT + technical * OVERALL_TECHNICAL_WEIGHT,
        1,
    )


def build_technical_criterion_rows(
    *,
    criteria: tuple[tuple[str, str, float], ...],
    scores_by_supplier: dict[str, dict[str, float]],
    supplier_names: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid, by_criterion in scores_by_supplier.items():
        name = supplier_names.get(sid, sid)
        for cid, label, weight_pct in criteria:
            s = float(by_criterion.get(cid, 3.0))
            contrib = round((s / 5.0) * weight_pct, 2)
            rows.append(
                {
                    "line_id": f"{sid}-{cid}",
                    "supplier_id": sid,
                    "supplier": name,
                    "criterion_id": cid,
                    "criterion": label,
                    "weight_pct": weight_pct,
                    "score_0_5": s,
                    "contribution_pts": contrib,
                    "evidence": f"Evaluator average on 0–5 scale; contributes {contrib:.1f} of 100 technical points.",
                }
            )
    return rows


def build_commercial_criterion_rows(
    *,
    criteria: tuple[tuple[str, str, float], ...],
    supplier_ids: list[str],
    supplier_names: dict[str, str],
    totals: dict[str, float],
    technical_scores: dict[str, float],
    commercial_subscores: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Commercial envelope: price uses QCBS formula; sub-criteria are narrative weights for demo."""
    lowest = min(totals.values()) if totals else 0.0
    rows: list[dict[str, Any]] = []
    subs = commercial_subscores or {}
    for sid in supplier_ids:
        name = supplier_names.get(sid, sid)
        total = float(totals.get(sid, 0.0))
        qualified = technical_scores.get(sid, 0.0) >= MIN_TECHNICAL_SCORE
        price_score = commercial_price_score(total, lowest, qualified=qualified)
        for cid, label, weight_pct in criteria:
            if cid == "C1":
                contrib = round(price_score * (weight_pct / 100.0), 2)
                note = (
                    f"Lowest qualified total SAR {lowest:,.0f}; this bid SAR {total:,.0f}. "
                    f"Commercial points for price = (lowest ÷ bid) × 100 = {price_score:.1f}, "
                    f"× {weight_pct:.0f}% envelope weight → {contrib:.1f} pts."
                )
                score_component = price_score
            else:
                sub = subs.get(sid, {}).get(cid, 85.0)
                contrib = round(sub * (weight_pct / 100.0), 2)
                score_component = sub
                note = f"Procurement assessment ({weight_pct:.0f}% of commercial envelope): {sub:.1f}."
            rows.append(
                {
                    "line_id": f"{sid}-{cid}",
                    "supplier_id": sid,
                    "supplier": name,
                    "criterion_id": cid,
                    "criterion": label,
                    "weight_pct": weight_pct,
                    "score_component": score_component,
                    "contribution_pts": contrib,
                    "qualified": qualified,
                    "evaluated_total": total,
                    "lowest_qualified_total": lowest,
                    "calculation_notes": note,
                }
            )
    return rows


def build_commercial_breakdown_rows(
    supplier_ids: list[str],
    supplier_names: dict[str, str],
    totals: dict[str, float],
    technical_scores: dict[str, float],
) -> list[dict[str, Any]]:
    lowest = min(totals.values()) if totals else 0.0
    rows: list[dict[str, Any]] = []
    for rank, sid in enumerate(
        sorted(
            supplier_ids,
            key=lambda s: commercial_price_score(
                totals.get(s, 0.0),
                lowest,
                qualified=technical_scores.get(s, 0.0) >= MIN_TECHNICAL_SCORE,
            ),
            reverse=True,
        ),
        start=1,
    ):
        total = float(totals.get(sid, 0.0))
        t_score = technical_scores.get(sid, 0.0)
        qualified = t_score >= MIN_TECHNICAL_SCORE
        c_score = commercial_price_score(total, lowest, qualified=qualified)
        rows.append(
            {
                "rank": rank,
                "supplier_id": sid,
                "supplier": supplier_names.get(sid, sid),
                "evaluated_total": total,
                "lowest_qualified_total": lowest,
                "technical_score": t_score,
                "qualified_for_commercial": qualified,
                "commercial_score": c_score,
                "formula_summary": (
                    "Qualified suppliers only (technical ≥ 70). "
                    f"commercial_score = lowest_price ÷ this_price × 100 "
                    f"= {lowest:,.0f} ÷ {total:,.0f} × 100 = {c_score:.1f}"
                    if qualified
                    else f"Not qualified — technical score {t_score:.1f} is below minimum {MIN_TECHNICAL_SCORE:.0f}."
                ),
            }
        )
    return rows


def commercial_envelope_score(criterion_rows: list[dict[str, Any]], supplier_id: str) -> float:
    return round(
        sum(
            float(r["contribution_pts"])
            for r in criterion_rows
            if r.get("supplier_id") == supplier_id
        ),
        1,
    )


def rfp_rubric_bundle(
    supplier_ids: list[str],
    supplier_names: dict[str, str],
    totals: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    tech_scores = {
        sid: technical_score_from_criteria(_RFP_DEMO_CRITERION_0_5.get(sid, {}), TECHNICAL_CRITERIA_RFP)
        for sid in supplier_ids
    }
    tech_rows = build_technical_criterion_rows(
        criteria=TECHNICAL_CRITERIA_RFP,
        scores_by_supplier=_RFP_DEMO_CRITERION_0_5,
        supplier_names=supplier_names,
    )
    comm_sub = {
        "SUP-11836": {"C2": 88.0, "C3": 90.0},
        "SUP-11564": {"C2": 92.0, "C3": 85.0},
        "SUP-12448": {"C2": 86.0, "C3": 88.0},
    }
    comm_criterion = build_commercial_criterion_rows(
        criteria=COMMERCIAL_CRITERIA_RFP,
        supplier_ids=supplier_ids,
        supplier_names=supplier_names,
        totals=totals,
        technical_scores=tech_scores,
        commercial_subscores=comm_sub,
    )
    comm_breakdown = build_commercial_breakdown_rows(
        supplier_ids, supplier_names, totals, tech_scores
    )
    return tech_rows, comm_criterion, comm_breakdown, tech_scores


def qq_rubric_bundle(
    supplier_ids: list[str],
    supplier_names: dict[str, str],
    totals: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    tech_scores = {
        sid: technical_score_from_criteria(_QQ_DEMO_CRITERION_0_5.get(sid, {}), TECHNICAL_CRITERIA_QQ)
        for sid in supplier_ids
    }
    tech_rows = build_technical_criterion_rows(
        criteria=TECHNICAL_CRITERIA_QQ,
        scores_by_supplier=_QQ_DEMO_CRITERION_0_5,
        supplier_names=supplier_names,
    )
    comm_sub = {sid: {"C2": 88.0, "C3": 86.0} for sid in supplier_ids}
    comm_criterion = build_commercial_criterion_rows(
        criteria=COMMERCIAL_CRITERIA_QQ,
        supplier_ids=supplier_ids,
        supplier_names=supplier_names,
        totals=totals,
        technical_scores=tech_scores,
        commercial_subscores=comm_sub,
    )
    comm_breakdown = build_commercial_breakdown_rows(
        supplier_ids, supplier_names, totals, tech_scores
    )
    return tech_rows, comm_criterion, comm_breakdown, tech_scores
