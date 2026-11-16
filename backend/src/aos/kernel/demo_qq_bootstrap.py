"""Full iPhone Quick Quote client demo (QQ-0001 / QQ-0013)."""

from __future__ import annotations

from pathlib import Path

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import clock, ids
from .demo_instance_backup import _delete_instance_tree
from .demo_qq_client_heal import heal_quick_quote_client_demo
from .org import OrgModel

ORG_ID = "org_demo"
SEAT = "seat_sourcing_poc"
TITLE = "1 x iPhone 17 Pro Max 512 GB purchase"


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


async def bootstrap_full_qq_demo(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    packs_dir: Path,
    instance_id: str = "QQ-0001",
    replace: bool = True,
) -> str:
    if replace:
        await _delete_instance_tree(conn, instance_id)

    pack_version_id = await _seat_pack_version(conn)
    now = clock.now()
    attrs = {"brief_version": 2, "shortlist_count": 3, "quote_count": 3, "invited_count": 3}
    await conn.execute(
        "insert into work.instances ("
        " id, org_id, workflow, pack_version_id, seat, seat_version, title, state, status,"
        " attributes, correlation_id, version, created_by, created_at, state_entered_at, raised_events"
        ") values ("
        " %s, %s, 'quick_quote', %s, %s, 1, %s, 'closed', 'closed',"
        " %s, %s, 1, 'noura', %s, %s, '[]'::jsonb"
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
        ("buyer", "noura", "rule"),
        ("requester", "faisal", "creation"),
        ("category_manager", "rami", "rule"),
    ):
        await conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, %s, %s, %s)",
            (instance_id, role, person_id, bound),
        )

    aid = ids.new_artifact_id()
    brief = {
        "title": TITLE,
        "quantity": 1,
        "specification": "Apple iPhone 17 Pro Max, 512 GB, black, without charger — facilities.",
        "delivery_date": "2026-12-01",
        "delivery_site": "Al Nakheel Mall, Dammam, Saudi Arabia",
        "category": "CAT-EUD",
    }
    from .demo_rfp_bootstrap import _hash

    bh = _hash(brief)
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'brief', '', 'Brief', 'final', 1)",
        (aid, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'person', 'faisal', '[]'::jsonb, '[]'::jsonb)",
        (aid, Jsonb(brief), bh),
    )

    # Minimal comparison so heal resolves awarded vendor SUP-11615
    cid = ids.new_artifact_id()
    cmp = {"rows": [{"rank": 1, "supplier": "SUP-11615", "unit_price": 5970, "total": 5970, "lead_time_days": 5, "score": 100}]}
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'comparison', '', 'Comparison', 'final', 1)",
        (cid, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'person', 'noura', '[]'::jsonb, '[]'::jsonb)",
        (cid, Jsonb(cmp), _hash(cmp)),
    )

    await heal_quick_quote_client_demo(conn, instance_id, org=org, packs_dir=packs_dir)
    return instance_id
