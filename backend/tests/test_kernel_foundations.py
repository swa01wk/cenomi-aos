"""M0 kernel foundations: organization seed, persona sessions, audit hash chain and the baseline schema.

The Postgres tests apply the real migrations to a scratch database and are skipped when no local
Postgres is reachable.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from aos.kernel import audit
from aos.kernel.auth import AuthError, issue_session, read_session, require_console
from aos.kernel.org import OrgModel, load_org, seed_sql
from aos.registry import validate_pack

from . import _pg

REPO = Path(__file__).resolve().parents[2]
ORG_FILE = REPO / "seed" / "org.yaml"


class OrgTests(unittest.TestCase):
    def test_seed_org_is_consistent(self) -> None:
        org = load_org(ORG_FILE)
        self.assertIn("noura", org.people)
        self.assertEqual(org.people["khalid"].team, "procurement/procurement")

    def test_inconsistent_org_is_rejected(self) -> None:
        raw = yaml.safe_load(ORG_FILE.read_text())
        raw["departments"]["procurement"]["teams"]["sourcing"]["owner"] = "ghost"
        with self.assertRaises(ValueError):
            OrgModel.model_validate(raw)

    def test_pack_owners_and_placement_check_against_org(self) -> None:
        org = load_org(ORG_FILE)
        report = validate_pack(REPO / "packs" / "procurement_demo", org=org.as_validation_org())
        self.assertTrue(report.ok, "\n".join(map(str, report.issues)))


K1, K2 = "k1-" + "x" * 40, "k2-" + "y" * 40


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.org = load_org(ORG_FILE)

    def test_persona_session_round_trip(self) -> None:
        claims = read_session(issue_session(self.org, "noura", K1), K1)
        self.assertEqual(claims["sub"], "noura")
        self.assertEqual(claims["org"], "org_demo")
        self.assertNotIn("participant_roles", claims, "participant roles are resolved server-side")

    def test_console_gate(self) -> None:
        require_console(read_session(issue_session(self.org, "head_of_procurement", K1), K1))
        with self.assertRaises(AuthError):
            require_console(read_session(issue_session(self.org, "faisal", K1), K1))

    def test_bad_signature_and_unknown_person(self) -> None:
        with self.assertRaises(AuthError):
            read_session(issue_session(self.org, "noura", K1), K2)
        with self.assertRaises(AuthError):
            issue_session(self.org, "mallory", K1)


def _chain(n: int) -> list[audit.AuditRecord]:
    recs, seq, head = [], 0, audit.GENESIS
    for i in range(n):
        r = audit.append(seq, head, org_id="org_demo", actor="kernel", action=f"test.step{i}", subject="QQ-0001",
                         correlation_id="corr_qq0001", data={"i": i, "nested": {"b": 2, "a": 1}},
                         occurred_at=f"2026-10-15T10:00:{i:02d}+00:00")
        recs.append(r)
        seq, head = r.seq, r.record_hash
    return recs


class AuditChainTests(unittest.TestCase):
    def test_intact_chain_verifies(self) -> None:
        report = audit.verify(_chain(6))
        self.assertTrue(report.intact)
        self.assertEqual(report.records, 6)

    def test_changed_content_is_found_at_that_record(self) -> None:
        recs = _chain(6)
        recs[3] = replace(recs[3], data={"i": 999})
        report = audit.verify(recs)
        self.assertFalse(report.intact)
        self.assertEqual(report.first_broken_seq, 4)

    def test_deleted_record_is_found(self) -> None:
        recs = _chain(6)
        del recs[2]
        report = audit.verify(recs)
        self.assertEqual(report.first_broken_seq, 3)

    def test_rehashed_forgery_breaks_the_next_link(self) -> None:
        recs = _chain(5)
        forged = replace(recs[1], actor="someone_else")
        recs[1] = replace(forged, record_hash=forged.compute_hash())
        report = audit.verify(recs)
        self.assertEqual(report.first_broken_seq, 3)

    def test_canonical_form_ignores_key_order(self) -> None:
        a = audit.AuditRecord("o", 1, "t", "x", "y", "z", data={"a": 1, "b": 2})
        b = audit.AuditRecord("o", 1, "t", "x", "y", "z", data={"b": 2, "a": 1})
        self.assertEqual(a.compute_hash(), b.compute_hash())


@unittest.skipUnless(_pg.available(), "no local Postgres")
class BaselineSchemaTests(unittest.TestCase):
    db: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.sql(seed_sql(load_org(ORG_FILE)))

    @classmethod
    def tearDownClass(cls) -> None:
        _pg.drop(cls.db)

    @classmethod
    def sql(cls, statement: str, *, check: bool = True, user: str | None = None) -> subprocess.CompletedProcess:
        body = "set timezone = 'UTC';\n" + statement
        if user:
            url = _pg.kernel_url(cls.db).replace("aos_kernel:aos_kernel_dev", f"{user}:{user}_dev", 1)
            return subprocess.run(["psql", url, "-q", "-v", "ON_ERROR_STOP=1", "-At"], input=body, text=True,
                                  capture_output=True, check=check)
        return _pg.admin_sql(cls.db, body, check=check)

    def test_six_schemas_exist(self) -> None:
        out = self.sql("select string_agg(nspname, ',' order by nspname) from pg_namespace "
                       "where nspname in ('org','registry','work','gov','evidence','lg_checkpoints');").stdout.strip()
        self.assertEqual(out, "evidence,gov,lg_checkpoints,org,registry,work")

    def test_seed_is_idempotent_and_complete(self) -> None:
        self.sql(seed_sql(load_org(ORG_FILE)))
        out = self.sql("select count(*) from org.people;").stdout.strip()
        self.assertEqual(out, str(len(load_org(ORG_FILE).people)))

    def test_audit_chain_round_trips_through_postgres(self) -> None:
        recs = _chain(4)
        rows = ",".join(
            f"('{r.org_id}', {r.seq}, '{r.occurred_at}', '{r.actor}', '{r.action}', '{r.subject}', "
            f"'{r.correlation_id}', '{json.dumps(r.data)}'::jsonb, '{r.prev_hash}', '{r.record_hash}')" for r in recs)
        self.sql("delete from evidence.audit_heads where false;"
                 f"insert into evidence.audit_events values {rows};")
        out = self.sql("select json_agg(json_build_object('org_id', org_id, 'seq', seq, "
                       "'occurred_at', to_char(occurred_at, 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"'), "
                       "'actor', actor, 'action', action, 'subject', subject, 'correlation_id', correlation_id, "
                       "'data', data, 'prev_hash', prev_hash, 'record_hash', record_hash) order by seq) "
                       "from evidence.audit_events where org_id = 'org_demo';").stdout.strip()
        back = [audit.AuditRecord(**r) for r in json.loads(out)]
        self.assertTrue(audit.verify(back).intact)

    def test_audit_is_append_only(self) -> None:
        r = audit.append(1000, audit.GENESIS, org_id="org_demo", actor="kernel", action="x", subject="y")
        self.sql(f"insert into evidence.audit_events values ('org_demo', {r.seq}, now(), 'kernel', 'x', 'y', null,"
                 f" '{{}}', '{r.prev_hash}', '{r.record_hash}');")
        upd = self.sql(f"update evidence.audit_events set actor = 'mallory' where seq = {r.seq};", check=False)
        self.assertNotEqual(upd.returncode, 0)
        self.assertIn("append-only", upd.stderr)
        dele = self.sql(f"delete from evidence.audit_events where seq = {r.seq};", check=False)
        self.assertIn("append-only", dele.stderr)

    def test_published_definitions_are_immutable(self) -> None:
        out = self.sql(
            "insert into registry.packs values ('org_demo', 'p_immut', 'head_of_procurement') on conflict do nothing;"
            "insert into registry.pack_versions(org_id, pack_name, version, digest, source, status, validation, created_by)"
            " values ('org_demo', 'p_immut', 1, 'd', 'test', 'published', '{}', 'platform_admin') returning id;")
        vid = out.stdout.strip().splitlines()[-1]
        self.sql(f"insert into registry.definitions values ('{vid}', 'Seat', 's', 1, '{{}}', 'd', 'f');")
        res = self.sql(f"update registry.definitions set spec = '{{\"x\":1}}' where pack_version_id = '{vid}';",
                       check=False)
        self.assertIn("immutable", res.stderr)

    def test_worker_role_cannot_read_business_state(self) -> None:
        res = self.sql("select count(*) from org.people;", user="aos_worker", check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("permission denied", res.stderr)
        ok = self.sql("create table lg_checkpoints.t_probe(x int); drop table lg_checkpoints.t_probe;",
                      user="aos_worker", check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_kernel_role_cannot_rewrite_audit(self) -> None:
        res = self.sql("update evidence.audit_events set actor = 'k' where false;", user="aos_kernel", check=False)
        self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
