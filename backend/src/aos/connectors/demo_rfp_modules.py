"""Module-level RFP pricing, benchmarks, and BAFO negotiation copy (demo)."""

from __future__ import annotations

import statistics
from typing import Any

from .demo_proposal_fill import demo_supplier_display_name

# Standard scope modules aligned with the master RFP (phase one).
RFP_SCOPE_MODULES: tuple[tuple[str, str], ...] = (
    ("MOD-01", "CMS core and bilingual content"),
    ("MOD-02", "Public marketing site UX"),
    ("MOD-03", "REST API and integrations"),
    ("MOD-04", "Hosting and DevOps (KSA)"),
    ("MOD-05", "UAT, training, and 12-month support"),
)

# Per-supplier module amounts (SAR). Rows must sum to demo proposal totals.
_MODULE_AMOUNTS: dict[str, dict[str, float]] = {
    "SUP-11836": {
        "MOD-01": 2_050_000,
        "MOD-02": 720_000,
        "MOD-03": 880_000,
        "MOD-04": 420_000,
        "MOD-05": 550_000,
    },
    "SUP-11564": {
        "MOD-01": 1_120_000,
        "MOD-02": 760_000,
        "MOD-03": 2_080_000,
        "MOD-04": 430_000,
        "MOD-05": 460_000,
    },
    "SUP-12448": {
        "MOD-01": 1_090_000,
        "MOD-02": 740_000,
        "MOD-03": 910_000,
        "MOD-04": 1_620_000,
        "MOD-05": 630_000,
    },
}

# After BAFO, vendors trim the lines procurement challenged.
_POST_BAFO_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "SUP-11564": {"MOD-03": -86_400},  # ~8% on API
    "SUP-12448": {"MOD-04": -99_200},  # ~16% on hosting
}


def demo_proposal_pricing_modules(supplier_id: str, *, post_bafo: bool = False) -> list[dict[str, Any]]:
    base = dict(_MODULE_AMOUNTS.get(supplier_id) or {})
    if post_bafo:
        for mid, delta in (_POST_BAFO_ADJUSTMENTS.get(supplier_id) or {}).items():
            if mid in base:
                base[mid] = round(base[mid] + delta, 2)
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    out: list[dict[str, Any]] = []
    for mid, label in RFP_SCOPE_MODULES:
        amount = base.get(mid, 0.0)
        out.append({"module_id": mid, "name": label, "amount": amount})
    return out


def _fair_benchmarks() -> dict[str, float]:
    by_module: dict[str, list[float]] = {mid: [] for mid, _ in RFP_SCOPE_MODULES}
    for sid in _MODULE_AMOUNTS:
        for mid, amount in _MODULE_AMOUNTS[sid].items():
            by_module[mid].append(amount)
    return {mid: round(statistics.median(vals), 2) for mid, vals in by_module.items() if vals}


def _variance_pct(quoted: float, fair: float) -> float:
    if fair <= 0:
        return 0.0
    return round((quoted - fair) / fair * 100, 1)


def _module_score(variance_pct: float) -> float:
    return round(max(0.0, min(100.0, 100.0 - abs(variance_pct) * 2.5)), 1)


def build_module_matrix_rows(*, post_bafo: bool = False) -> list[dict[str, Any]]:
    fair = _fair_benchmarks()
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    rows: list[dict[str, Any]] = []
    for mid, label in RFP_SCOPE_MODULES:
        amounts = {
            sid: demo_proposal_pricing_modules(sid, post_bafo=post_bafo)
            for sid in _MODULE_AMOUNTS
        }
        by_sid = {
            sid: next((m["amount"] for m in mods if m["module_id"] == mid), 0.0)
            for sid, mods in amounts.items()
        }
        fair_amt = fair[mid]
        high_sid = max(by_sid, key=by_sid.get)
        high_amt = by_sid[high_sid]
        high_name = demo_supplier_display_name(high_sid)
        vpct = _variance_pct(high_amt, fair_amt)
        talking = (
            f"{high_name} quoted SAR {high_amt:,.0f} for {label}; "
            f"fair benchmark ~SAR {fair_amt:,.0f} ({vpct:+.1f}% vs median of submissions)."
        )
        rows.append(
            {
                "module_id": mid,
                "module_name": names[mid],
                "fair_benchmark": fair_amt,
                "tamkeen_sar": by_sid.get("SUP-11836", 0),
                "rawabi_sar": by_sid.get("SUP-11564", 0),
                "peninsula_sar": by_sid.get("SUP-12448", 0),
                "high_supplier": high_name,
                "high_amount": high_amt,
                "vs_fair_pct": vpct,
                "bafo_talking_point": talking,
            }
        )
    return rows


def build_module_score_rows(*, post_bafo: bool = False) -> list[dict[str, Any]]:
    fair = _fair_benchmarks()
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    rows: list[dict[str, Any]] = []
    for sid in sorted(_MODULE_AMOUNTS.keys()):
        name = demo_supplier_display_name(sid)
        for mod in demo_proposal_pricing_modules(sid, post_bafo=post_bafo):
            mid = str(mod["module_id"])
            quoted = float(mod["amount"])
            fair_amt = fair.get(mid, quoted)
            var_sar = round(quoted - fair_amt, 2)
            vpct = _variance_pct(quoted, fair_amt)
            rows.append(
                {
                    "module_line_id": f"{mid}:{sid}",
                    "module_id": mid,
                    "module_name": names.get(mid, mod.get("name", mid)),
                    "supplier_id": sid,
                    "supplier": name,
                    "quoted_amount": quoted,
                    "fair_benchmark": fair_amt,
                    "variance_sar": var_sar,
                    "variance_pct": vpct,
                    "module_score": _module_score(vpct),
                }
            )
    return rows


def suppliers_with_bafo_outliers(*, min_vs_fair_pct: float = 8.0) -> list[str]:
    """Suppliers with at least one module priced above fair by min_vs_fair_pct."""
    fair = _fair_benchmarks()
    flagged: set[str] = set()
    for sid in _MODULE_AMOUNTS:
        for mod in demo_proposal_pricing_modules(sid, post_bafo=False):
            mid = str(mod["module_id"])
            quoted = float(mod["amount"])
            if _variance_pct(quoted, fair.get(mid, quoted)) >= min_vs_fair_pct:
                flagged.add(sid)
                break
    return sorted(flagged)


def build_bafo_email_body(supplier_id: str) -> str:
    name = demo_supplier_display_name(supplier_id)
    fair = _fair_benchmarks()
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    lines = [
        f"Dear {name} team,",
        "",
        "Thank you for your formal proposal. Before we run a best-and-final offer (BAFO) round, "
        "procurement needs alignment on module-level pricing compared with the other shortlisted bidders.",
        "",
    ]
    for mod in demo_proposal_pricing_modules(supplier_id, post_bafo=False):
        mid = str(mod["module_id"])
        quoted = float(mod["amount"])
        fair_amt = fair.get(mid, quoted)
        vpct = _variance_pct(quoted, fair_amt)
        if vpct < 6.0:
            continue
        label = names.get(mid, mod.get("name", mid))
        lines.append(
            f"• **{label} ({mid})** — you quoted SAR {quoted:,.0f}. Based on peer submissions, "
            f"a fair reference is about SAR {fair_amt:,.0f}. Why is your price at this level? "
            f"We would expect movement toward the benchmark in your BAFO."
        )
    if len(lines) <= 5:
        lines.append(
            "• Please confirm your module breakdown still matches the master RFP scope and "
            "share any BAFO improvement you can offer on total cost."
        )
    lines.extend(
        [
            "",
            "Please reply on this thread with updated module pricing or a brief commercial rationale.",
            "",
            "Regards,",
            "Noura Al-Rashid",
            "Head of Procurement — Cenomi",
        ]
    )
    return "\n".join(lines)


def build_bafo_email_content(supplier_id: str) -> dict[str, Any]:
    name = demo_supplier_display_name(supplier_id)
    return {
        "supplier_id": supplier_id,
        "to": f"rfp+{supplier_id.lower()}@vendor.example",
        "subject": f"BAFO — module pricing review ({name})",
        "body": build_bafo_email_body(supplier_id),
    }


def _sar(amount: float) -> str:
    return f"SAR {amount:,.0f}"


def format_proposal_modules_chat_summary(supplier_id: str) -> str:
    """Thread text: one vendor's module lines (for demo chat history)."""
    name = demo_supplier_display_name(supplier_id)
    mods = demo_proposal_pricing_modules(supplier_id, post_bafo=False)
    lines = [
        f"**{name}** submitted a full commercial proposal with **module-level** pricing:",
        "",
    ]
    for mod in mods:
        lines.append(f"- **{mod['module_id']}** {mod['name']}: {_sar(float(mod['amount']))}")
    total = sum(float(mod["amount"]) for mod in mods)
    lines.append("")
    lines.append(f"**Proposal total:** {_sar(total)} (also on the Reply tab under Responses).")
    return "\n".join(lines)


def format_module_comparison_chat_block() -> str:
    """Thread text: all three vendors side-by-side per module (matches Module comparison tab)."""
    rows = build_module_matrix_rows(post_bafo=False)
    lines = [
        "I built the **Module comparison** sheet across **all three** shortlisted vendors "
        "(Tamkeen, Rawabi, Peninsula). Fair benchmark = median of their quotes per module:",
        "",
    ]
    for row in rows:
        lines.append(
            f"**{row['module_id']}** — {row['module_name']}\n"
            f"- Fair (median): {_sar(float(row['fair_benchmark']))}\n"
            f"- Tamkeen: {_sar(float(row['tamkeen_sar']))} · "
            f"Rawabi: {_sar(float(row['rawabi_sar']))} · "
            f"Peninsula: {_sar(float(row['peninsula_sar']))}\n"
            f"- Outlier: **{row['high_supplier']}** at {_sar(float(row['high_amount']))} "
            f"({float(row['vs_fair_pct']):+.1f}% vs fair)"
        )
        lines.append("")
    lines.append(
        "Open **Documents → Module comparison** and **Module scores** in the work panel for the full grid."
    )
    return "\n".join(lines)


def format_module_outliers_chat_block() -> str:
    """Highlight rows that drive BAFO (API + hosting)."""
    fair = _fair_benchmarks()
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    highlights: list[str] = []
    for mid in ("MOD-03", "MOD-04"):
        label = names.get(mid, mid)
        fair_amt = fair.get(mid, 0)
        parts: list[str] = []
        for sid in sorted(_MODULE_AMOUNTS.keys()):
            amt = _MODULE_AMOUNTS[sid].get(mid, 0)
            name = demo_supplier_display_name(sid)
            vpct = _variance_pct(amt, fair_amt)
            parts.append(f"{name} {_sar(amt)} ({vpct:+.1f}%)")
        highlights.append(
            f"**{mid} {label}** — fair ~{_sar(fair_amt)}. " + " · ".join(parts)
        )
    return (
        "**Module scores** flag commercial outliers vs peers (used before BAFO):\n\n"
        + "\n\n".join(highlights)
        + "\n\nProcurement will ask high bidders *why* their module price exceeds the peer benchmark."
    )


def format_bafo_hook_chat_line(supplier_id: str) -> str:
    """Short negotiation example for chat: why X when fair is Y."""
    name = demo_supplier_display_name(supplier_id)
    fair = _fair_benchmarks()
    names = {mid: label for mid, label in RFP_SCOPE_MODULES}
    for mod in demo_proposal_pricing_modules(supplier_id, post_bafo=False):
        mid = str(mod["module_id"])
        quoted = float(mod["amount"])
        fair_amt = fair.get(mid, quoted)
        if _variance_pct(quoted, fair_amt) < 8.0:
            continue
        label = names.get(mid, mod.get("name", mid))
        return (
            f"BAFO draft for **{name}**: on **{label} ({mid})** you quoted {_sar(quoted)}; "
            f"Rawabi and Tamkeen imply a fair reference around {_sar(fair_amt)} — "
            f"please explain the gap or improve in your best-and-final."
        )
    return f"BAFO draft for **{name}** is ready under **Drafts → BAFO**."
