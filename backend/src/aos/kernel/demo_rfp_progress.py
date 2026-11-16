"""Chat progress lines during demo RFP supplier simulation."""

from __future__ import annotations

from psycopg import AsyncConnection

from aos.connectors.demo_proposal_fill import demo_supplier_display_name
from aos.connectors.demo_rfp_modules import format_proposal_modules_chat_summary

from .org import OrgModel
from .progress import post_agent_progress_turn


async def post_supplier_sim_progress(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    *,
    supplier_id: str,
    kind: str,
    question_index: int | None = None,
) -> None:
    name = demo_supplier_display_name(supplier_id)
    if kind == "ack":
        text = f"**{name}** acknowledged the RFP invitation (demo mail sync)."
    elif kind == "question":
        text = (
            f"**{name}** sent clarification question {question_index or 1} — "
            "check **question_lane** (commercial → procurement, technical → category manager) "
            "and the draft answer in proposal Notes."
        )
    elif kind == "proposal":
        text = format_proposal_modules_chat_summary(supplier_id)
    else:
        return
    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [str(r[0]) for r in await roles_cur.fetchall()]
    from .conversation import text_blocks

    await post_agent_progress_turn(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        seat_name="seat_sourcing_poc",
        seat_version=1,
        blocks=text_blocks(text),
        audience={"roles": roles},
    )
