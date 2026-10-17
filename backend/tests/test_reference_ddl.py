"""The reference DDL in docs/specs/backend/ddl applies cleanly on top of the M0 migrations and keeps its guards.

When a milestone moves a ddl file into backend/migrations, delete it from docs/specs/backend/ddl and drop its
entry from TABLES here (the table checks can move to that milestone's own tests).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests import _pg

DDL = Path(__file__).resolve().parents[2] / "docs" / "specs" / "backend" / "ddl"

TABLES = {
    "0004": ["work.instance_transitions", "work.regions", "work.timers", "work.demo_clock", "work.notifications"],
    "0005": ["gov.policy_decisions", "gov.approvals", "gov.approval_steps", "work.action_executions",
             "work.inbound_messages"],
    "0006": ["gov.kill_switches", "gov.credential_revocations", "evidence.outcome_records"],
}

UNIQUE_INDEXES = ["approval_steps_distinct"]

CHECKS = [  # (table, fragment of the check definition)
    ("gov.kill_switches", "lifted_by <> activated_by"),
]


@unittest.skipUnless(_pg.available(), "needs a local Postgres")
class ReferenceDDLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        for f in sorted(DDL.glob("*.sql")):
            _pg.admin_sql(cls.db, f.read_text())

    @classmethod
    def tearDownClass(cls) -> None:
        _pg.drop(cls.db)

    def q(self, sql: str) -> str:
        return _pg.admin_sql(self.db, sql).stdout.strip()

    def test_every_file_is_listed(self) -> None:
        self.assertEqual(sorted(TABLES), sorted(p.name[:4] for p in DDL.glob("*.sql")))

    def test_tables_exist(self) -> None:
        for prefix, tables in TABLES.items():
            for t in tables:
                with self.subTest(file=prefix, table=t):
                    self.assertEqual(self.q(f"select to_regclass('{t}') is not null"), "t")

    def test_partial_unique_indexes(self) -> None:
        for name in UNIQUE_INDEXES:
            with self.subTest(index=name):
                self.assertEqual(self.q(
                    f"select count(*) from pg_indexes where indexname = '{name}' and indexdef like '%UNIQUE%'"), "1")

    def test_guard_checks(self) -> None:
        for table, fragment in CHECKS:
            with self.subTest(table=table):
                defs = self.q(f"select string_agg(pg_get_constraintdef(oid), ' | ') from pg_constraint "
                              f"where conrelid = '{table}'::regclass and contype = 'c'")
                self.assertIn(fragment, defs)

    def test_worker_role_stays_out_of_kernel_tables(self) -> None:
        for prefix, tables in TABLES.items():
            for t in tables:
                with self.subTest(table=t):
                    self.assertEqual(self.q(
                        f"select has_table_privilege('aos_worker', '{t}', 'select')"), "f")


if __name__ == "__main__":
    unittest.main()
