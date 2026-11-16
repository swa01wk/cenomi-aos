"""Backfill full RFP client-demo artifacts and chat on existing jobs (RFP-0001, etc.)."""

from __future__ import annotations

import os
from pathlib import Path

from psycopg import AsyncConnection

from aos.connectors.demo_rfp_modules import (
    build_bafo_email_content,
    build_module_matrix_rows,
    build_module_score_rows,
    format_module_comparison_chat_block,
    format_module_outliers_chat_block,
    format_proposal_modules_chat_summary,
    suppliers_with_bafo_outliers,
)

from .conversation import insert_agent_turn, insert_person_turn, text_blocks
from .demo_artifact_upsert import artifact_row_sample, has_artifact, upsert_artifact
from .demo_pack_repin import align_instance_pack_to_seat
from aos.connectors.demo_rfp_spec_stage import (
    build_procurement_validation_rows,
    build_rfp_upload_manifest,
    build_scoring_method_agreement,
    build_template_compliance_rows,
)

from .demo_rfp_bootstrap import (
    SUPPLIERS,
    _commercial_eval_rows,
    _evaluation_rows,
    _rfp_eval_data,
    _technical_eval_rows,
)
from .org import OrgModel


def _demo_enabled() -> bool:
    return os.environ.get("AOS_DEMO", "0").strip().lower() in ("1", "true", "yes")


async def _has_turn(conn: AsyncConnection, instance_id: str, needle: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.turns where instance_id = %s"
        " and (blocks::text like %s or coalesce(client_turn_id, '') like %s) limit 1",
        (instance_id, f"%{needle}%", f"%{needle}%"),
    )
    return await cur.fetchone() is not None


async def _ensure_participant(
    conn: AsyncConnection, instance_id: str, role: str, person_id: str
) -> None:
    cur = await conn.execute(
        "select 1 from work.participants where instance_id = %s and role = %s limit 1",
        (instance_id, role),
    )
    if await cur.fetchone() is not None:
        return
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, %s, %s, 'rule')",
        (instance_id, role, person_id),
    )


async def heal_sourcing_rfp_client_demo(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    _ = org, packs_dir
    if not _demo_enabled():
        return False
    cur = await conn.execute(
        "select workflow, state from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or str(row[0]) != "sourcing_rfp":
        return False
    state = str(row[1])
    if state not in ("awaiting_proposals", "comparison", "bafo", "ordering", "closed"):
        return False

    await align_instance_pack_to_seat(conn, org_id=org.organization.id, instance_id=instance_id)

    sample = await artifact_row_sample(conn, instance_id, "rfp_evaluation")
    modern_eval = sample is not None and "weighted_score" in sample and "score" not in sample
    sample_comm = await artifact_row_sample(conn, instance_id, "rfp_eval_commercial")
    has_comm = sample_comm is not None and "commercial_score" in sample_comm
    sample_mod = await artifact_row_sample(conn, instance_id, "rfp_module_matrix")
    has_mod = sample_mod is not None and "fair_benchmark" in sample_mod
    has_rubric = await has_artifact(conn, instance_id, "technical_criterion_scores")
    has_spec = await has_artifact(conn, instance_id, "scoring_method_agreement")
    artifacts_complete = modern_eval and has_comm and has_mod and has_rubric and has_spec

    await _ensure_participant(conn, instance_id, "category_manager", "rami")
    await _ensure_participant(conn, instance_id, "requester", "faisal")

    if not artifacts_complete:
        await upsert_artifact(
            conn,
            instance_id,
            "rfp_procurement_validation",
            "",
            "RFP validation",
            {"rows": build_procurement_validation_rows()},
        )
        await upsert_artifact(
            conn,
            instance_id,
            "rfp_template_compliance",
            "",
            "Template check",
            {"rows": build_template_compliance_rows()},
        )
        await upsert_artifact(
            conn,
            instance_id,
            "scoring_method_agreement",
            "",
            "Scoring agreement",
            build_scoring_method_agreement(),
        )
        await upsert_artifact(
            conn,
            instance_id,
            "rfp_upload_manifest",
            "",
            "RFP uploads",
            build_rfp_upload_manifest(),
        )
        await upsert_artifact(
            conn, instance_id, "rfp_module_matrix", "", "Module comparison", {"rows": build_module_matrix_rows()}
        )
        await upsert_artifact(
            conn, instance_id, "rfp_module_scores", "", "Module scores", {"rows": build_module_score_rows()}
        )
        await upsert_artifact(
            conn, instance_id, "rfp_eval_commercial", "", "Commercial evaluation", {"rows": _commercial_eval_rows()}
        )
        await upsert_artifact(
            conn, instance_id, "rfp_eval_technical", "", "Technical evaluation", {"rows": _technical_eval_rows()}
        )
        await upsert_artifact(
            conn, instance_id, "rfp_evaluation", "", "Weighted evaluation", {"rows": _evaluation_rows()}
        )
        tech_rows, comm_rows, policy, _, _ = _rfp_eval_data()
        await upsert_artifact(
            conn, instance_id, "technical_criterion_scores", "", "Technical rubric", {"rows": tech_rows}
        )
        await upsert_artifact(
            conn, instance_id, "commercial_criterion_scores", "", "Commercial rubric", {"rows": comm_rows}
        )
        await upsert_artifact(conn, instance_id, "eval_scoring_policy", "", "Scoring policy", policy)
        await conn.execute(
            "update work.artifacts set name = 'Weighted evaluation'"
            " where instance_id = %s and artifact_type = 'rfp_evaluation'",
            (instance_id,),
        )
        for sid in suppliers_with_bafo_outliers():
            await upsert_artifact(
                conn,
                instance_id,
                "bafo_email",
                sid,
                f"Bafo Email {sid}",
                build_bafo_email_content(sid),
                status="draft",
            )

    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [str(r[0]) for r in await roles_cur.fetchall()]

    if not await _has_turn(conn, instance_id, "demo-noura-sendback"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="noura",
            text=(
                "Specification stage: sent master RFP **back to Faisal** (round 1) for BoQ upload. "
                "See **Template check** and **RFP uploads** in Documents."
            ),
            client_turn_id=f"demo-heal-noura-sendback-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "demo-faisal-scoring-agree"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="faisal",
            text="Uploaded BoQ v2 and confirmed **Scoring agreement** (70/30 QCBS) with Procurement.",
            client_turn_id=f"demo-heal-faisal-scoring-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "Specification stage artifacts"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(
                "**Specification stage** stays in Documents throughout the journey: **RFP validation**, "
                "**Template check**, **Scoring agreement**, and **RFP uploads**. Evaluation uses the same "
                "rubrics (Show scoring rubric on eval tabs)."
            ),
            audience_roles=roles,
            attempt_id=None,
        )

    if not await _has_turn(conn, instance_id, "Line-item comparison") and not await _has_turn(
        conn, instance_id, "Module comparison"
    ):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(format_module_comparison_chat_block()),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "Module scores** flag"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(format_module_outliers_chat_block()),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "question_lane"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(
                "**Commercial** clarification questions are routed to **Noura** (procurement). "
                "**Technical** questions go to **Rami** (category manager). "
                "Each proposal Notes tab shows the draft answer and **question_lane**."
            ),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "weighted_score"):
        lines = [
            "**Commercial eval**, **Technical eval**, and **Weighted eval** (30% / 70%) for "
            "Tamkeen, Rawabi, and Peninsula:",
            "",
        ]
        for erow in _evaluation_rows():
            lines.append(
                f"- **{erow['supplier']}** — commercial {erow['commercial_score']}, technical "
                f"{erow['technical_score']}, weighted **{erow['weighted_score']}**"
            )
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks("\n".join(lines)),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "commercial** clarification"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="noura",
            text="Approved and sent **commercial** clarification to Rawabi (payment terms on support SLA).",
            client_turn_id=f"demo-heal-noura-comm-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "technical** clarification"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="rami",
            text="Approved and sent **technical** clarification to Tamkeen (CMS bilingual launch scope).",
            client_turn_id=f"demo-heal-rami-tech-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "Send BAFO"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="noura",
            text=(
                "BAFO challenges module pricing (why X vs peer fair Y). Use **Send BAFO** and "
                "**Complete BAFO round**; then **Rami** recommends vendor for award."
            ),
            client_turn_id=f"demo-heal-bafo-{instance_id}",
            audience_roles=roles,
        )

    for sid in SUPPLIERS:
        needle = format_proposal_modules_chat_summary(sid).split("\n", 1)[0][:50]
        if await _has_turn(conn, instance_id, needle):
            continue
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(format_proposal_modules_chat_summary(sid)),
            audience_roles=roles,
            attempt_id=None,
        )

    return True
