"""aos validate: the demo pack passes, and each broken variant fails with the right code.

Runs under plain ``python -m unittest`` as well as pytest.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from aos.cli import main as cli_main
from aos.registry import validate_pack
from aos.registry.loader import parse_yaml

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "packs" / "procurement_demo"
ORG = yaml.safe_load((REPO / "seed" / "org.yaml").read_text())


class PackCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.pack = self.tmp / "pack"
        shutil.copytree(PACK, self.pack)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def edit(self, rel: str, fn) -> None:
        path = self.pack / rel
        doc = parse_yaml(path.read_text())
        fn(doc)
        path.write_text(yaml.safe_dump(doc, sort_keys=False))

    def assertFailsWith(self, code: str) -> None:
        report = validate_pack(self.pack, org=ORG)
        self.assertFalse(report.ok, "expected the pack to fail validation")
        self.assertIn(code, report.codes(), "\n".join(map(str, report.issues)))


class DemoPackPasses(unittest.TestCase):
    def test_demo_pack_is_valid(self) -> None:
        report = validate_pack(PACK, org=ORG)
        self.assertTrue(report.ok, "\n".join(map(str, report.issues)))
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.counts["WorkflowDefinition"], 1)
        self.assertEqual(report.counts["Skill"], 5)

    def test_cli_exit_codes(self) -> None:
        self.assertEqual(cli_main(["validate", str(PACK), "--org", str(REPO / "seed" / "org.yaml")]), 0)
        self.assertEqual(cli_main(["validate", str(REPO / "no-such-pack")]), 1)

    def test_on_key_is_a_string_not_a_boolean(self) -> None:
        doc = parse_yaml("transitions: [{from: a, to: b, on: x}]\nflag: yes\nreal: true")
        self.assertIn("on", doc["transitions"][0])
        self.assertEqual(doc["flag"], "yes")
        self.assertIs(doc["real"], True)

    def test_digest_is_stable(self) -> None:
        self.assertEqual(validate_pack(PACK).digest, validate_pack(PACK).digest)


class BrokenPacksFail(PackCase):
    def test_template_targets_role_without_its_work_type(self) -> None:
        # Acceptance test: a Task template sending work to a role that cannot do its Work Type fails.
        self.edit("roles/sourcing_agent.yaml",
                  lambda d: d["spec"].__setitem__("work_types", ["analysis", "document_draft", "outbound_communication"]))
        self.assertFailsWith("E_ROLE_WORKTYPE")

    def test_domain_field_on_kernel_kind_is_rejected(self) -> None:
        self.edit("seats/seat_sourcing_poc.yaml", lambda d: d["spec"].__setitem__("preferred_supplier", "najd"))
        self.assertFailsWith("E_SCHEMA")

    def test_guard_on_undeclared_attribute(self) -> None:
        def fn(d):
            d["spec"]["transitions"][1]["guard"] = "attr.vendor_count >= 3"
        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_ATTRIBUTE")

    def test_policy_condition_on_unknown_state(self) -> None:
        def fn(d):
            d["spec"]["rules"][0]["conditions"][0] = 'workflow.reached("nowhere")'
        self.edit("policies/quick_quote_gates.yaml", fn)
        self.assertFailsWith("E_REF")

    def test_supervised_seat_cannot_send_without_approval(self) -> None:
        def fn(d):
            for g in d["spec"]["grants"]:
                if g["resource"] == "mailbox" and "send" in g["actions"]:
                    g["effect"] = "ALLOW"
        self.edit("policies/sourcing_supervised.yaml", fn)
        self.assertFailsWith("E_UNGOVERNED_EFFECT")

    def test_require_approval_needs_a_rule_naming_approvers(self) -> None:
        self.edit("policies/quick_quote_gates.yaml",
                  lambda d: d["spec"].__setitem__("rules", [r for r in d["spec"]["rules"] if r["id"] != "po_create"]))
        self.assertFailsWith("E_NO_APPROVAL_CHAIN")

    def test_dead_end_and_unreachable_states(self) -> None:
        def fn(d):
            d["spec"]["transitions"] = [t for t in d["spec"]["transitions"] if t["from"] != "comparison"]
        self.edit("workflows/quick_quote.yaml", fn)
        report = validate_pack(self.pack, org=ORG)
        self.assertIn("E_DEAD_END", report.codes())
        self.assertIn("E_UNREACHABLE", report.codes())
        self.assertIn("E_NO_FINAL", report.codes())

    def test_task_completed_must_name_a_template_of_the_state(self) -> None:
        def fn(d):
            d["spec"]["transitions"][2]["on"] = "task.completed.po_create"
        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_EVENT")

    def test_decision_needs_a_participant(self) -> None:
        def fn(d):
            d["spec"]["transitions"][0]["by"] = "cfo"
        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_REF")

    def test_shareable_artifact_cannot_hold_internal_fields(self) -> None:
        def fn(d):
            d["spec"]["fields"]["budget_hint"] = {"type": "money", "classification": "internal"}
        self.edit("artifact_types/rfq_email.yaml", fn)
        self.assertFailsWith("E_CLASSIFICATION")

    def test_view_columns_must_exist(self) -> None:
        self.edit("artifact_types/comparison.yaml",
                  lambda d: d["spec"]["view"]["columns"].append("discount"))
        self.assertFailsWith("E_VIEW_COLUMN")

    def test_unknown_view_type(self) -> None:
        self.edit("artifact_types/brief.yaml", lambda d: d["spec"]["view"].__setitem__("type", "kanban"))
        self.assertFailsWith("E_SCHEMA")

    def test_missing_instructions_file(self) -> None:
        (self.pack / "skills" / "quote_triage" / "instructions.md").unlink()
        self.assertFailsWith("E_FILE")

    def test_committed_effect_needs_reconcile_tool(self) -> None:
        self.edit("connectors/mock_erp.yaml", lambda d: d["spec"]["tools"]["create_po"].pop("reconcile_with"))
        self.assertFailsWith("E_SCHEMA")

    def test_unknown_owner_with_org(self) -> None:
        self.edit("verifiers/leak_check.yaml", lambda d: d["metadata"].__setitem__("owner", "someone_else"))
        self.assertFailsWith("E_OWNER")

    def test_authority_profile_version_pin(self) -> None:
        self.edit("seats/seat_sourcing_poc.yaml",
                  lambda d: d["spec"].__setitem__("authority_profile", "sourcing_supervised@2"))
        self.assertFailsWith("E_VERSION")

    def test_duplicate_names(self) -> None:
        shutil.copy(self.pack / "verifiers" / "leak_check.yaml", self.pack / "verifiers" / "leak_check_copy.yaml")
        self.assertFailsWith("E_DUPLICATE")

    def test_skill_requests_unknown_tool(self) -> None:
        self.edit("skills/rfq_authoring/skill.yaml", lambda d: d["spec"]["may_request"].append("upload_to_drive"))
        self.assertFailsWith("E_REF")


if __name__ == "__main__":
    unittest.main()
