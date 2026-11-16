"""One-shot full RFP client demo job (all personas, rich chat, evaluation ready)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.connectors.demo_proposal_fill import (
    build_demo_proposal_content,
    build_demo_question_content,
    demo_clarification_bank,
    demo_supplier_display_name,
)
from aos.connectors.demo_rfp_spec_stage import (
    build_procurement_validation_rows,
    build_rfp_upload_manifest,
    build_scoring_method_agreement,
    build_template_compliance_rows,
)
from aos.connectors.demo_eval_rubrics import (
    OVERALL_COMMERCIAL_WEIGHT,
    OVERALL_TECHNICAL_WEIGHT,
    commercial_envelope_score,
    rfp_rubric_bundle,
    scoring_policy_content,
    weighted_combined,
)
from aos.connectors.demo_rfp_modules import (
    build_bafo_email_content,
    build_module_matrix_rows,
    build_module_score_rows,
    format_bafo_hook_chat_line,
    format_module_comparison_chat_block,
    format_module_outliers_chat_block,
    format_proposal_modules_chat_summary,
    suppliers_with_bafo_outliers,
)

QUESTIONS_PER_SUPPLIER = 3

from . import clock, ids
from .conversation import insert_agent_turn, insert_person_turn, text_blocks
from .demo_instance_backup import _delete_instance_tree
from .demo_master_rfp_content import TITLE, demo_master_rfp_content
from .org import OrgModel

SUPPLIERS = ("SUP-11564", "SUP-11836", "SUP-12448")
ORG_ID = "org_demo"
SEAT = "seat_sourcing_poc"


def _hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _seat_pack_version(conn: AsyncConnection) -> str:
    cur = await conn.execute(
        "select pack_version_id from registry.seats"
        " where org_id = %s and name = %s order by version desc limit 1",
        (ORG_ID, SEAT),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError("seat_sourcing_poc not found — run make sync-pack-docker")
    return str(row[0])


def _brief_content() -> dict[str, Any]:
    return {
        "title": TITLE,
        "category": "CAT-IT-DEV",
        "quantity": 1,
        "specification": (
            "Bilingual public marketing site (Arabic/English), CMS, tenant and operations content, "
            "lead forms, REST API for mobile apps. Hosting in Saudi Arabia. Phased rollout ~10 months."
        ),
        "delivery_date": "2027-05-02",
        "delivery_site": "Saudi Arabia",
        "vendor_reply_deadline": "5 days",
        "quality_signoff": "CDO and category manager for scope clarifications",
        "attachments": [],
    }


def _supplier_rows() -> list[dict[str, Any]]:
    rows = []
    for i, sid in enumerate(SUPPLIERS, start=1):
        name = demo_supplier_display_name(sid)
        rows.append(
            {
                "rank": i,
                "supplier": name,
                "supplier_id": sid,
                "email": f"rfp+{sid.lower()}@vendor.example",
                "past_pos": 4 - i,
                "on_time_pct": 92.0 - i * 2,
                "points_asl": 20,
                "points_history": 25,
                "points_delivery": 27,
                "points_total": 72 - i,
                "selected": True,
            }
        )
    return rows


def _rfp_totals() -> dict[str, float]:
    totals: dict[str, float] = {}
    for sid in SUPPLIERS:
        prop = build_demo_proposal_content(
            sid,
            "Commercial proposal submitted with CMS, API, and 12-month support.",
            received_at=clock.iso_z(clock.now()),
            kind="proposal",
        )
        totals[sid] = float(prop["total"])
    return totals


_RFP_EVAL_CACHE: dict[str, Any] | None = None


def _rfp_eval_data() -> tuple[list[dict], list[dict], list[dict], dict[str, float], dict[str, float]]:
    global _RFP_EVAL_CACHE
    if _RFP_EVAL_CACHE is None:
        names = {sid: demo_supplier_display_name(sid) for sid in SUPPLIERS}
        totals = _rfp_totals()
        tech_rows, comm_rows, _, tech_scores = rfp_rubric_bundle(SUPPLIERS, names, totals)
        comm_scores = {sid: commercial_envelope_score(comm_rows, sid) for sid in SUPPLIERS}
        _RFP_EVAL_CACHE = {
            "tech_rows": tech_rows,
            "comm_rows": comm_rows,
            "tech_scores": tech_scores,
            "comm_scores": comm_scores,
            "policy": scoring_policy_content(envelope_label="RFP"),
        }
    c = _RFP_EVAL_CACHE
    return c["tech_rows"], c["comm_rows"], c["policy"], c["tech_scores"], c["comm_scores"]


def _eval_triplet(sid: str, rank: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Commercial row, technical row, weighted summary row for one supplier."""
    name = demo_supplier_display_name(sid)
    prop = build_demo_proposal_content(
        sid,
        "Commercial proposal submitted with CMS, API, and 12-month support.",
        received_at=clock.iso_z(clock.now()),
        kind="proposal",
    )
    _, _, _, tech_scores, comm_scores = _rfp_eval_data()
    c_score = comm_scores.get(sid, 85.0)
    t_score = tech_scores.get(sid, 85.0)
    weighted = weighted_combined(c_score, t_score)
    commercial = {
        "rank": rank,
        "supplier": name,
        "unit_price": prop["total"],
        "total": prop["total"],
        "lead_time_days": prop["lead_time_days"],
        "warranty_months": prop.get("warranty_months", 12),
        "commercial_score": c_score,
        "notes": (
            "Commercial envelope from price (QCBS) plus terms and delivery criteria. "
            "Open **Scoring rubric and calculation** for the line-by-line breakdown."
        ),
    }
    technical = {
        "rank": rank,
        "supplier": name,
        "supplier_id": sid,
        "technical_score": t_score,
        "notes": (
            "Technical score from criterion rubric (0–5 per PRD criteria). "
            "Open **Scoring rubric and calculation** below the sheet for the full breakdown."
        ),
    }
    combined = {
        "rank": rank,
        "supplier": name,
        "supplier_id": sid,
        "unit_price": prop["total"],
        "total": prop["total"],
        "lead_time_days": prop["lead_time_days"],
        "commercial_score": c_score,
        "technical_score": t_score,
        "weighted_score": weighted,
        "commercial_weight": OVERALL_COMMERCIAL_WEIGHT,
        "technical_weight": OVERALL_TECHNICAL_WEIGHT,
    }
    return commercial, technical, combined


def _evaluation_rows() -> list[dict[str, Any]]:
    order = [("SUP-11836", 1), ("SUP-11564", 2), ("SUP-12448", 3)]
    return [_eval_triplet(sid, rank)[2] for sid, rank in order]


def _commercial_eval_rows() -> list[dict[str, Any]]:
    order = [("SUP-11836", 1), ("SUP-11564", 2), ("SUP-12448", 3)]
    return [_eval_triplet(sid, rank)[0] for sid, rank in order]


def _technical_eval_rows() -> list[dict[str, Any]]:
    order = [("SUP-11836", 1), ("SUP-11564", 2), ("SUP-12448", 3)]
    return [_eval_triplet(sid, rank)[1] for sid, rank in order]


async def _insert_artifact(
    conn: AsyncConnection,
    *,
    instance_id: str,
    artifact_type: str,
    key: str,
    name: str,
    status: str,
    content: dict[str, Any],
    produced_by: str,
    produced_kind: str = "person",
) -> tuple[str, int]:
    aid = ids.new_artifact_id()
    ch = _hash(content)
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, %s, %s, %s, %s, 1)",
        (aid, instance_id, artifact_type, key, name, status),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, %s, %s, '[]'::jsonb, '[]'::jsonb)",
        (aid, Jsonb(content), ch, produced_kind, produced_by),
    )
    return aid, 1


async def _append_artifact_version(
    conn: AsyncConnection,
    *,
    artifact_id: str,
    version: int,
    content: dict[str, Any],
    produced_by: str,
    produced_kind: str = "person",
) -> None:
    ch = _hash(content)
    await conn.execute(
        "update work.artifacts set latest_version = %s where id = %s",
        (version, artifact_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, %s, %s, %s, %s, %s, '[]'::jsonb, '[]'::jsonb)",
        (artifact_id, version, Jsonb(content), ch, produced_kind, produced_by),
    )


async def _seed_turns(
    conn: AsyncConnection,
    instance_id: str,
    *,
    roles: list[str],
) -> None:
    """Chronological story for Noura, Samir (CDO), Rami, and the sourcing agent."""
    base = datetime.now(UTC) - timedelta(hours=2)
    seq = 0

    async def agent(text: str) -> None:
        nonlocal seq
        seq += 1
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id=SEAT,
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(text),
            audience_roles=roles,
            attempt_id=None,
        )

    async def person(pid: str, text: str, client_id: str) -> None:
        nonlocal seq
        seq += 1
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id=pid,
            text=text,
            client_turn_id=client_id,
            audience_roles=roles,
        )

    await person(
        "noura",
        "Run a formal RFP for the Cenomi Malls public website redesign — bilingual CMS, REST API, KSA hosting, "
        "~10 months. CDO must approve the master RFP before any vendor mail goes out.",
        "demo-noura-1",
    )
    await agent(
        "I'll run this as a formal **sourcing_rfp** job. I captured category **IT development**, delivery in Saudi Arabia, "
        "and a five-day proposal window (demo: minutes). Next I'll draft the brief and shortlist integrators from ERP."
    )
    await agent(
        "Brief **v2** is ready and the shortlist has **three** IT-DEV suppliers (Rawabi, Tamkeen, Peninsula). "
        "Next: specification stage — validate the RFP package, template compliance, and **lock scoring method** "
        "with the requester before CDO approval."
    )
    await agent(
        "**Procurement validation** (Documents → RFP validation): BoQ/modules, contract terms, SLAs, scope boundary, "
        "and **fixed-price** model checked. One gap: bill of quantities needed a requester upload."
    )
    await person(
        "noura",
        "Sending the draft master RFP **back to Faisal** (round 1) — BoQ missing for module pricing. "
        "Requester can upload their own spreadsheet or add sections; agent re-checks the template.",
        "demo-noura-sendback",
    )
    await person(
        "faisal",
        "Uploaded **Cenomi_Web_BoQ_MOD_v2.xlsx** and scope addendum. Please merge into Master RFP v2.",
        "demo-faisal-upload",
    )
    await agent(
        "**Template compliance** (Documents → Template check): all required sections for IT integrator RFP are "
        "**present** or **user_added** after upload. Agent suggested dual-envelope submission instructions — added."
    )
    await person(
        "noura",
        "Scoring method agreed with Faisal: **70/30 QCBS**, min technical **70**, criterion rubric as in "
        "**Scoring agreement**. Comparison basis locked before issue.",
        "demo-noura-scoring-agree",
    )
    await person(
        "faisal",
        "Confirmed scoring and comparison basis on behalf of the business. Proceed to CDO approval.",
        "demo-faisal-scoring-agree",
    )
    await agent(
        "The **Master RFP** is in **Documents → Master RFP** (agent draft + uploads in **RFP uploads**). "
        "**Scoring agreement** is visible to the requester and Procurement. Samir (CDO) approves before invitations."
    )
    await person(
        "cdo",
        "Opened **Documents → Master RFP** — scope, evaluation criteria, and timeline look correct for a "
        "mall-wide public site program. **Review and approve master RFP** is confirmed; Noura may release invitations.",
        "demo-cdo-1",
    )
    await agent(
        "**Samir (CDO)** approved the master RFP. Invitation drafts are ready for Noura to send to all three suppliers."
    )
    await person("noura", "Invitations sent to all three shortlisted suppliers.", "demo-noura-2")
    await agent(
        "All three suppliers **acknowledged** receipt by email. Clarification questions follow — "
        "**commercial** questions go to **Noura** (procurement); **technical** questions to **Rami** (category manager)."
    )
    for sid in SUPPLIERS:
        name = demo_supplier_display_name(sid)
        await agent(f"**{name}** acknowledged the RFP invitation (inbound email captured under **Responses**).")
        bank = demo_clarification_bank(sid)[:QUESTIONS_PER_SUPPLIER]
        for q_idx, (question, answer, lane) in enumerate(bank, start=1):
            route = "**Noura** (commercial)" if lane == "commercial" else "**Rami** (technical)"
            await agent(
                f"**{name}** sent a **{lane}** clarification (question {q_idx}):\n\n"
                f"> {question}\n\n"
                f"Draft answer is in proposal **Notes** for {route} to approve and send."
            )
            if lane == "commercial":
                await person(
                    "noura",
                    f"Approved and sent commercial clarification to {name} (question {q_idx}):\n\n{answer}",
                    f"demo-noura-{sid}-q{q_idx}",
                )
            else:
                await person(
                    "rami",
                    f"Approved and sent technical clarification to {name} (question {q_idx}):\n\n{answer}",
                    f"demo-rami-{sid}-q{q_idx}",
                )
    for sid in SUPPLIERS:
        await agent(format_proposal_modules_chat_summary(sid))
    await agent(format_module_comparison_chat_block())
    await agent(format_module_outliers_chat_block())
    await agent(
        "**Commercial** and **technical** evaluation sheets are saved, with a **weighted** summary "
        "(30% commercial / 70% technical per PRD) across **Tamkeen, Rawabi, and Peninsula** — criterion rubrics in Documents."
    )
    await person(
        "noura",
        "Confirmed **commercial module review** — compared all three bids line-by-line on MOD-01 through MOD-05. "
        "Peninsula is high on **MOD-04 hosting**; Rawabi on **MOD-03 API**. Moving to BAFO on those modules.",
        "demo-noura-commercial-eval",
    )
    await person(
        "rami",
        "Reviewed **technical eval** for all three vendors (architecture, delivery, bilingual CMS). "
        "Rawabi leads slightly on technical score; Tamkeen is strongest on weighted commercial after module variance.",
        "demo-rami-technical-eval",
    )
    for sid in suppliers_with_bafo_outliers():
        await agent(format_bafo_hook_chat_line(sid))
    await person(
        "noura",
        "BAFO drafts are under **Drafts → BAFO · …** — each names the module, your price, and the fair peer reference. "
        "I'll approve **Send BAFO** in the thread next, then **Complete BAFO round** before Rami recommends award.",
        "demo-noura-bafo",
    )


async def bootstrap_full_rfp_demo(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    packs_dir: Path,
    instance_id: str = "RFP-0001",
    replace: bool = True,
) -> str:
    """Create a complete RFP at Evaluation with chat history for Noura, CDO, and Rami."""
    _ = packs_dir
    if replace:
        await _delete_instance_tree(conn, instance_id)

    pack_version_id = await _seat_pack_version(conn)
    now = clock.now()
    attrs = {
        "brief_version": 2,
        "shortlist_count": 3,
        "invited_count": 3,
        "proposal_count": 3,
        "ack_count": 3,
        "detail_signal": 1,
    }
    await conn.execute(
        "insert into work.instances ("
        " id, org_id, workflow, pack_version_id, seat, seat_version, title, state, status,"
        " attributes, correlation_id, version, created_by, created_at, state_entered_at, raised_events"
        ") values ("
        " %s, %s, 'sourcing_rfp', %s, %s, 1, %s, 'bafo', 'running',"
        " %s, %s, 8, 'noura', %s, %s, '[]'::jsonb"
        ")",
        (
            instance_id,
            ORG_ID,
            pack_version_id,
            SEAT,
            TITLE,
            Jsonb(attrs),
            f"demo-{instance_id}",
            now,
            now,
        ),
    )
    for role, person_id, bound in (
        ("buyer", "noura", "creation"),
        ("requester", "faisal", "rule"),
        ("procurement_approver", "cdo", "rule"),
        ("category_manager", "rami", "rule"),
    ):
        await conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, %s, %s, %s)",
            (instance_id, role, person_id, bound),
        )

    roles = ["buyer", "requester", "procurement_approver", "category_manager"]
    await _seed_turns(conn, instance_id, roles=roles)

    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="brief",
        key="",
        name="Brief",
        status="final",
        content=_brief_content(),
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="supplier_list",
        key="",
        name="Supplier List",
        status="final",
        content={"rows": _supplier_rows()},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="master_rfp",
        key="main",
        name="Master RFP",
        status="final",
        content=demo_master_rfp_content(),
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_procurement_validation",
        key="",
        name="RFP validation",
        status="final",
        content={"rows": build_procurement_validation_rows()},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_template_compliance",
        key="",
        name="Template check",
        status="final",
        content={"rows": build_template_compliance_rows()},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="scoring_method_agreement",
        key="",
        name="Scoring agreement",
        status="final",
        content=build_scoring_method_agreement(),
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_upload_manifest",
        key="",
        name="RFP uploads",
        status="final",
        content=build_rfp_upload_manifest(),
        produced_by="faisal",
    )
    for sid in SUPPLIERS:
        name = demo_supplier_display_name(sid)
        await _insert_artifact(
            conn,
            instance_id=instance_id,
            artifact_type="rfp_invitation",
            key=sid,
            name=f"Rfp Invitation {sid}",
            status="final",
            content={
                "to": f"rfp+{sid.lower()}@vendor.example",
                "subject": f"RFP: {TITLE} [{sid}]",
                "body": f"Dear {name},\n\nPlease find Cenomi's formal RFP attached.\n\nReply deadline: 5 days.",
                "supplier_id": sid,
            },
            produced_by="noura",
        )
        ts = clock.iso_z(now)
        aid, ver = await _insert_artifact(
            conn,
            instance_id=instance_id,
            artifact_type="proposal",
            key=sid,
            name=f"Proposal {sid}",
            status="final",
            content=build_demo_proposal_content(
                sid,
                "",
                received_at=ts,
                kind="ack",
            ),
            produced_by="noura",
        )
        for q_idx in range(1, QUESTIONS_PER_SUPPLIER + 1):
            ver += 1
            await _append_artifact_version(
                conn,
                artifact_id=aid,
                version=ver,
                content=build_demo_question_content(sid, q_idx, received_at=ts),
                produced_by="noura",
            )
        ver += 1
        await _append_artifact_version(
            conn,
            artifact_id=aid,
            version=ver,
            content=build_demo_proposal_content(
                sid,
                "Commercial proposal submitted with CMS, API, and 12-month support.",
                received_at=ts,
                kind="proposal",
            ),
            produced_by="noura",
        )

    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_module_matrix",
        key="",
        name="Module comparison",
        status="final",
        content={"rows": build_module_matrix_rows(post_bafo=False)},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_module_scores",
        key="",
        name="Module scores",
        status="final",
        content={"rows": build_module_score_rows(post_bafo=False)},
        produced_by="noura",
    )
    for sid in suppliers_with_bafo_outliers():
        await _insert_artifact(
            conn,
            instance_id=instance_id,
            artifact_type="bafo_email",
            key=sid,
            name=f"Bafo Email {sid}",
            status="draft",
            content=build_bafo_email_content(sid),
            produced_by="noura",
        )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_eval_commercial",
        key="",
        name="Commercial evaluation",
        status="final",
        content={"rows": _commercial_eval_rows()},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_eval_technical",
        key="",
        name="Technical evaluation",
        status="final",
        content={"rows": _technical_eval_rows()},
        produced_by="noura",
    )
    tech_rows, comm_rows, policy, _, _ = _rfp_eval_data()
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="technical_criterion_scores",
        key="",
        name="Technical rubric",
        status="final",
        content={"rows": tech_rows},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="commercial_criterion_scores",
        key="",
        name="Commercial rubric",
        status="final",
        content={"rows": comm_rows},
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="eval_scoring_policy",
        key="",
        name="Scoring policy",
        status="final",
        content=policy,
        produced_by="noura",
    )
    await _insert_artifact(
        conn,
        instance_id=instance_id,
        artifact_type="rfp_evaluation",
        key="",
        name="Weighted evaluation",
        status="draft",
        content={"rows": _evaluation_rows()},
        produced_by="noura",
    )

    for template, skill, work_type in (
        ("rfp_evaluation", "rfp_evaluation", "analysis"),
        ("bafo_authoring", "bafo_negotiation", "document_draft"),
    ):
        tid = ids.new_task_id()
        await conn.execute(
            "insert into work.tasks ("
            " id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts"
            ") values (%s, %s, 'task', %s, %s, %s, 'COMPLETED', '{}', 'demo', 3)",
            (tid, instance_id, template, skill, work_type),
        )

    from .demo_bafo import open_next_bafo_pending

    await open_next_bafo_pending(conn, org, instance_id, packs_dir=packs_dir)

    return instance_id
