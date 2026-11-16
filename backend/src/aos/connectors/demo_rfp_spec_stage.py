"""Demo: specification / Master RFP stage — procurement validation, template compliance, scoring agreement."""

from __future__ import annotations

from typing import Any

from aos.connectors.demo_eval_rubrics import (
    MIN_TECHNICAL_SCORE,
    OVERALL_COMMERCIAL_WEIGHT,
    OVERALL_TECHNICAL_WEIGHT,
    SCORE_ANCHORS,
    TECHNICAL_CRITERIA_RFP,
)

RFP_TEMPLATE_TYPE = "IT systems integrator — fixed-price services"


def build_procurement_validation_rows() -> list[dict[str, Any]]:
    """Validate against procurement conditions (BoQ, contract, SLA, scope, pricing model)."""
    return [
        {
            "check_id": "PC-01",
            "area": "Bill of quantities / pricing structure",
            "status": "pass",
            "detail": (
                "Module-level BoQ attached (MOD-01–MOD-05) with fixed unit rates per phase. "
                "Procurement validated like-for-like modules across suppliers."
            ),
        },
        {
            "check_id": "PC-02",
            "area": "Contract terms",
            "status": "pass",
            "detail": "Cenomi standard RFP terms referenced; liability cap, PDPL, and IP assignment clauses present.",
        },
        {
            "check_id": "PC-03",
            "area": "SLAs and service levels",
            "status": "pass",
            "detail": "Hypercare P1/P2 targets, warranty 12 months, and CMS uptime commitment in scope section.",
        },
        {
            "check_id": "PC-04",
            "area": "Scope boundary",
            "status": "pass",
            "detail": "In/out of scope explicit (no tenant portal auth, no native apps in phase 1).",
        },
        {
            "check_id": "PC-05",
            "area": "Fixed-price model",
            "status": "pass",
            "detail": (
                "Lump-sum fixed price for defined modules; change control for additions. "
                "Not time-and-materials for core delivery."
            ),
        },
        {
            "check_id": "PC-06",
            "area": "Comparison basis",
            "status": "pass",
            "detail": "Agreed 70/30 QCBS with minimum technical 70 — see Scoring agreement document.",
        },
    ]


def build_template_compliance_rows() -> list[dict[str, Any]]:
    """Template check for IT integrator RFP — agent draft vs upload, missing sections."""
    return [
        {
            "section_id": "S1",
            "section": "Executive summary",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "present",
            "source": "agent",
            "suggestion": "",
        },
        {
            "section_id": "S2",
            "section": "Bill of quantities / module pricing",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "user_added",
            "source": "upload",
            "suggestion": "Requester uploaded BoQ spreadsheet after round 1 send-back.",
        },
        {
            "section_id": "S3",
            "section": "Contract and commercial terms",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "present",
            "source": "agent",
            "suggestion": "",
        },
        {
            "section_id": "S4",
            "section": "SLA and support matrix",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "present",
            "source": "agent",
            "suggestion": "",
        },
        {
            "section_id": "S5",
            "section": "Evaluation criteria and weights (agreed)",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "present",
            "source": "agent",
            "suggestion": "Aligned with Scoring agreement before CDO approval.",
        },
        {
            "section_id": "S6",
            "section": "Data residency and security",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "present",
            "source": "agent",
            "suggestion": "",
        },
        {
            "section_id": "S7",
            "section": "Submission instructions (dual envelope)",
            "required_for_type": RFP_TEMPLATE_TYPE,
            "status": "suggested",
            "source": "agent",
            "detail": "Agent suggested separate technical vs commercial submission — incorporated in invitation.",
        },
    ]


def build_scoring_method_agreement() -> dict[str, Any]:
    tech_criteria = "; ".join(f"{label} ({w:.0f}%)" for _, label, w in TECHNICAL_CRITERIA_RFP)
    return {
        "template_type": RFP_TEMPLATE_TYPE,
        "comparison_basis": (
            "Two-envelope QCBS: technical criteria scored 0–5 per evaluator, commercial on normalized "
            "fixed-price modules. Combined ranking uses agreed weights below."
        ),
        "agreed_technical_weight": OVERALL_TECHNICAL_WEIGHT,
        "agreed_commercial_weight": OVERALL_COMMERCIAL_WEIGHT,
        "min_technical_score": MIN_TECHNICAL_SCORE,
        "technical_criteria_summary": tech_criteria,
        "commercial_basis": "Total evaluated fixed price across BoQ modules; QCBS price formula after qualification.",
        "scale_0_5": "; ".join(SCORE_ANCHORS),
        "requester_confirmed": "Faisal Al-Mutairi (Facilities / project sponsor) — agreed in chat before issue.",
        "procurement_confirmed": "Noura Al-Rashid (Procurement) — locked before CDO approval.",
        "approval_rounds_config": "2 rounds: (1) procurement validation send-back to requester for BoQ upload; "
        "(2) CDO master RFP approval. Configurable to 1 round for simple goods.",
        "upload_support": (
            "Requester may upload their own RFP or BoQ (Excel/PDF). Agent checks sections against "
            f"template **{RFP_TEMPLATE_TYPE}** and lists gaps for user add or re-upload."
        ),
        "notes": (
            "Scoring method frozen at this agreement; changes after supplier issue would require re-approval."
        ),
    }


def build_rfp_upload_manifest() -> dict[str, Any]:
    return {
        "template_type": RFP_TEMPLATE_TYPE,
        "uploaded_files": [
            {
                "name": "Cenomi_Web_BoQ_MOD_v2.xlsx",
                "kind": "bill_of_quantities",
                "version": 2,
                "uploaded_by": "faisal",
                "notes": "Added after procurement send-back (round 1).",
            },
            {
                "name": "Facilities_Sponsor_Scope_Addendum.pdf",
                "kind": "scope_addendum",
                "version": 1,
                "uploaded_by": "faisal",
                "notes": "Optional; merged into Master RFP v2.",
            },
        ],
        "agent_generated_master": "Master RFP v2 (Documents tab) — baseline draft; uploads merged by agent.",
    }
