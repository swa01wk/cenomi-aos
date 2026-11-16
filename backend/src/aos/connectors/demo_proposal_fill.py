"""Deterministic demo payloads for RFP supplier replies (POC reliability)."""

from __future__ import annotations

from typing import Any

from .proposal_reply_parse import ReplyKind, classify_rfp_reply

# supplier segment id -> (display name, total SAR, lead days, warranty months)
def demo_supplier_display_name(supplier_id: str) -> str:
    row = _DEMO_BY_SUPPLIER.get(supplier_id)
    return row[0] if row else supplier_id


def demo_supplier_id_from_display_name(name: str) -> str | None:
    target = (name or "").strip()
    for sid, (display, *_rest) in _DEMO_BY_SUPPLIER.items():
        if display == target:
            return sid
    return None


_DEMO_BY_SUPPLIER: dict[str, tuple[str, float, int, int]] = {
    "SUP-11564": ("Rawabi Digital Services", 4_850_000, 300, 12),
    "SUP-11836": ("Tamkeen IT Outsourcing", 4_620_000, 280, 12),
    "SUP-12448": ("Peninsula Software Labs", 4_990_000, 310, 12),
}


def _excerpt_from_body(body: str, *, fallback: str) -> str:
    text = (body or "").strip()
    if not text:
        return fallback
    if "truncated" in text.lower() and len(text) < 400:
        return fallback
    return text[:8000]


def _question_draft_answer(body: str) -> str:
    return (
        "Draft answer for the supplier (category manager review): Scope includes bilingual CMS, tenant "
        "content modules, lead forms, and REST API for mobile apps as described in the master RFP. "
        "Salesforce CRM integration is out of scope for phase one unless added via change control. "
        "Please confirm this addresses your question."
    )


QuestionLane = str  # "commercial" | "technical"

_DEMO_QUESTIONS: dict[str, list[tuple[str, str, QuestionLane]]] = {
    "SUP-11564": [
        (
            "Could you confirm whether Salesforce CRM integration is required in phase one?",
            "Salesforce is out of scope for phase one. The REST API covers lead capture; CRM sync can be "
            "added via change control if needed.",
            "technical",
        ),
        (
            "What content migration volume should we plan for (pages and media)?",
            "Plan for up to 2,000 CMS pages and 50 GB media across EN/AR, migrated from the current site "
            "with a two-week UAT window.",
            "technical",
        ),
        (
            "Will Cenomi provide staging environments and SSO for our delivery team?",
            "Yes — staging and UAT URLs plus Azure AD SSO for named integrator staff are included in the "
            "master RFP infrastructure assumptions.",
            "technical",
        ),
    ],
    "SUP-11836": [
        (
            "Is bilingual (Arabic/English) CMS mandatory for all tenant-facing modules on day one?",
            "All public marketing and tenant portal modules must launch bilingual; admin-only screens may "
            "follow in a patch release if agreed in writing.",
            "technical",
        ),
        (
            "What SLA do you expect for P1 production incidents after go-live?",
            "Target 4-hour response and 24-hour workaround for P1 during the first 12 months of support.",
            "commercial",
        ),
        (
            "Are third-party analytics tags (GA4, Meta pixel) in scope for the marketing site?",
            "Yes — implement via tag manager with Cenomi approval on each container publish.",
            "technical",
        ),
    ],
    "SUP-12448": [
        (
            "Should the mobile app REST API follow a specific OpenAPI version or gateway?",
            "OpenAPI 3.1 documented APIs behind the existing API gateway; no GraphQL requirement.",
            "technical",
        ),
        (
            "Is penetration testing and security review before launch mandatory?",
            "Yes — one external pen test and remediation sprint before production cutover.",
            "technical",
        ),
        (
            "What is the preferred hosting region for CMS and API workloads?",
            "Primary hosting in KSA (Azure UAE North DR acceptable for non-PII static assets only).",
            "technical",
        ),
    ],
}

_DEFAULT_QUESTIONS: list[tuple[str, str, QuestionLane]] = [
    (
        "Please confirm integration boundaries for phase one.",
        "Phase one covers the modules listed in the master RFP; other systems via change control.",
        "technical",
    ),
    (
        "What are the acceptance criteria for UAT sign-off?",
        "UAT scripts in the RFP annex must pass with no open P1/P2 defects.",
        "technical",
    ),
    (
        "Can you confirm standard payment terms are net-30 from PO issuance?",
        "Cenomi standard procurement terms are net-30; early payment discounts may be proposed separately.",
        "commercial",
    ),
]


def classify_question_lane(question_text: str) -> QuestionLane:
    """Route vendor clarifications: commercial to procurement, technical to category manager."""
    t = (question_text or "").lower()
    commercial_hints = (
        "payment",
        "net-30",
        "invoice",
        "sla",
        "penalty",
        "liquidated",
        "contract",
        "pricing",
        "commercial",
        "warranty period",
        "support fee",
    )
    if any(h in t for h in commercial_hints):
        return "commercial"
    return "technical"


def demo_clarification_bank(supplier_id: str) -> list[tuple[str, str, QuestionLane]]:
    """(question, draft answer, lane) for demo bootstrap."""
    return list(_DEMO_QUESTIONS.get(supplier_id) or _DEFAULT_QUESTIONS)


def build_demo_question_content(
    supplier_id: str,
    question_index: int,
    *,
    received_at: str,
) -> dict[str, Any]:
    """Demo clarification question (1-based index) with category-manager draft answer in notes."""
    name = demo_supplier_display_name(supplier_id)
    bank = _DEMO_QUESTIONS.get(supplier_id) or _DEFAULT_QUESTIONS
    idx = max(0, min(question_index - 1, len(bank) - 1))
    question, draft_answer, lane = bank[idx]
    excerpt = f"Dear Cenomi team,\n\n{question}\n\nRegards,\n{name}"
    reviewer = "procurement (buyer)" if lane == "commercial" else "category manager (Rami)"
    content: dict[str, Any] = {
        "supplier": name,
        "reply_kind": "question",
        "question_lane": lane,
        "acknowledged": False,
        "received_at": received_at,
        "lead_time_days": 0,
        "unit_price": 0,
        "total": 0,
        "reply_excerpt": excerpt,
        "notes": (
            f"Clarification {question_index} of {len(bank)} ({lane}) — draft for {reviewer} to review "
            f"before send: {draft_answer}"
        ),
    }
    _, _total, lead, warranty = _DEMO_BY_SUPPLIER.get(supplier_id, (name, 0, 300, 12))
    content["lead_time_days"] = lead
    content["warranty_months"] = warranty
    return content


def build_demo_proposal_content(
    supplier_id: str,
    email_body: str,
    *,
    received_at: str,
    kind: ReplyKind | None = None,
) -> dict[str, Any]:
    """Fill a complete proposal artifact for demo — any inbound email maps to rich mock data."""
    resolved_kind: ReplyKind = kind or classify_rfp_reply(email_body or "")
    name, total, lead, warranty = _DEMO_BY_SUPPLIER.get(
        supplier_id, (supplier_id, 4_500_000, 300, 12)
    )

    ack_excerpt = (
        f"Dear Cenomi team,\n\nWe confirm receipt of the RFP invitation and intend to submit our "
        f"full proposal within the stated deadline.\n\nBest regards,\n{name}"
    )
    excerpt = _excerpt_from_body(
        email_body,
        fallback=ack_excerpt if resolved_kind == "ack" else f"{name} replied on the RFP thread.",
    )

    content: dict[str, Any] = {
        "supplier": name,
        "reply_kind": resolved_kind,
        "acknowledged": resolved_kind == "ack",
        "received_at": received_at,
        "lead_time_days": lead,
        "warranty_months": warranty,
        "reply_excerpt": excerpt,
    }

    if resolved_kind == "ack":
        content["unit_price"] = 0
        content["total"] = 0
        content["notes"] = "Acknowledgement recorded — full proposal expected before the deadline."
    elif resolved_kind == "question":
        lane = classify_question_lane(email_body)
        content["question_lane"] = lane
        content["unit_price"] = 0
        content["total"] = 0
        reviewer = "procurement" if lane == "commercial" else "category manager"
        content["notes"] = (
            f"Supplier asked for a {lane} clarification. "
            f"Agent draft for {reviewer} review: {_question_draft_answer(email_body)}"
        )
    else:
        content["unit_price"] = total
        content["total"] = total
        from .demo_rfp_modules import demo_proposal_pricing_modules

        content["pricing_modules"] = demo_proposal_pricing_modules(supplier_id, post_bafo=False)
        content["notes"] = "Commercial proposal captured from supplier reply (demo mock pricing)."

    return content


def is_agent_placeholder_proposal(content: dict[str, Any]) -> bool:
    """Detect failed agent triage rows that should be replaced by demo fill."""
    ex = str(content.get("reply_excerpt") or "").lower()
    notes = str(content.get("notes") or "").lower()
    if "truncated" in ex or "truncated" in notes:
        return True
    if "can't populate" in notes or "cannot populate" in notes:
        return True
    if "not visible" in ex and content.get("total") in (0, 0.0, None):
        return True
    return False
