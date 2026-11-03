"""payload_match: PO read back from the ERP matches the approved po_payload."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from aos.kernel.verify import Verdict


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _payload_doc(outputs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for out in outputs:
        if str(out.get("artifact_type") or "") == "po_payload":
            content = out.get("content")
            return content if isinstance(content, dict) else None
    return None


def _erp_po(receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(receipts):
        tool = str(entry.get("tool") or "")
        content = entry.get("content")
        if not isinstance(content, dict):
            continue
        if tool == "find_po" and content.get("found") and isinstance(content.get("po"), dict):
            return content["po"]
        if tool == "create_po" and content.get("id"):
            return content
    return None


def _line_total(lines: list[Any]) -> Decimal:
    total = Decimal("0")
    for line in lines:
        if not isinstance(line, dict):
            continue
        qty = _money(line.get("quantity"))
        price = _money(line.get("unit_price"))
        if qty is not None and price is not None:
            total += qty * price
    return total


def verify(inp: dict[str, Any]) -> tuple[Verdict, list[str]]:
    payload = _payload_doc(inp.get("outputs") or [])
    if payload is None:
        return "FAIL", ["No po_payload output was saved on this task."]
    erp = _erp_po(inp.get("tool_receipts") or [])
    if erp is None:
        return "REWORK", ["No purchase order was read back from the ERP yet."]

    findings: list[str] = []
    if str(payload.get("supplier_id") or "") != str(erp.get("supplier_id") or ""):
        findings.append("Supplier on the PO does not match the approved payload.")
    if str(payload.get("reference") or "") != str(erp.get("reference") or ""):
        findings.append("PO reference does not match the approved payload.")
    payload_amount = _money(payload.get("po_amount"))
    erp_amount = _money(erp.get("total"))
    if payload_amount is not None and erp_amount is not None and payload_amount != erp_amount:
        findings.append("PO total does not match the approved amount.")
    payload_lines = payload.get("lines")
    erp_lines = erp.get("lines")
    if isinstance(payload_lines, list) and isinstance(erp_lines, list):
        if len(payload_lines) != len(erp_lines):
            findings.append("PO line count does not match the approved payload.")
        elif _line_total(payload_lines) != _line_total(erp_lines):
            findings.append("PO line totals do not match the approved payload.")
    need_by = str(payload.get("need_by") or "")
    erp_need = str(erp.get("need_by") or "")
    if need_by and erp_need and need_by[:10] != erp_need[:10]:
        findings.append("Need-by date on the PO does not match the approved payload.")

    return ("FAIL", findings) if findings else ("PASS", [])
