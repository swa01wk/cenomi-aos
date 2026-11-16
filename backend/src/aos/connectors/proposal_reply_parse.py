"""Classify and parse supplier replies on RFP invitation threads."""

from __future__ import annotations

import re
from typing import Any, Literal

from .quote_reply_parse import append_parse_hints, parse_quote_reply_text

ReplyKind = Literal["ack", "question", "proposal"]

_ACK_PHRASES = (
    "confirm receipt",
    "confirmed receipt",
    "acknowledge receipt",
    "acknowledged",
    "we acknowledge",
    "thank you for inviting",
    "thank you for the invitation",
    "intend to submit",
    "intend to respond",
    "we intend to",
    "will submit our proposal",
    "will respond to this rfp",
)

_QUESTION_HINTS = (
    "clarification",
    "could you confirm",
    "please confirm",
    "please advise",
    "kindly clarify",
    "we have a question",
    "questions regarding",
)


def _has_substantive_pricing(text: str) -> bool:
    lower = text.lower()
    if re.search(r"(?i)total\s*(?:project\s*)?price\s*[:\-]\s*sar\s*[\d,]{4,}", lower):
        return True
    if re.search(r"(?i)sar\s*[\d,]{5,}", lower):
        return True
    parsed = parse_quote_reply_text(text)
    unit = parsed.get("unit_price")
    total = parsed.get("total")
    if unit is not None and float(unit) >= 1000:
        return True
    if total is not None and float(total) >= 1000:
        return True
    return False


def classify_rfp_reply(text: str) -> ReplyKind:
    """First-line demo behaviour: receipt/ack replies before full commercial proposals."""
    if not text or not text.strip():
        return "ack"
    lower = text.replace("\r\n", "\n").lower()
    if _has_substantive_pricing(text):
        return "proposal"
    if any(p in lower for p in _QUESTION_HINTS) or (
        "?" in text and not any(p in lower for p in _ACK_PHRASES)
    ):
        return "question"
    if any(p in lower for p in _ACK_PHRASES):
        return "ack"
    if re.search(r"\back\b", lower):
        return "ack"
    return "ack"


def parse_proposal_reply_text(text: str) -> dict[str, Any]:
    """Pricing fields when present; always infer reply_kind."""
    kind = classify_rfp_reply(text)
    parsed: dict[str, Any] = {"reply_kind": kind, "acknowledged": kind == "ack"}
    if kind == "proposal":
        parsed.update(parse_quote_reply_text(text))
        parsed["acknowledged"] = False
    return parsed
