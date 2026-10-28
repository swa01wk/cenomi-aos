"""Task contract assembly from pinned pack Skills (M2-AG-01)."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from aos.kernel import contracts
from aos.kernel.org import load_org
from aos.registry.loader import load_pack, parse_yaml

REPO = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO / "packs"
PACK = PACKS_DIR / "procurement_demo"
ORG = load_org(REPO / "seed" / "org.yaml")


def _defs():
    loaded = load_pack(PACK)
    out: dict[str, dict[str, dict]] = {}
    for kind, bucket in loaded.objects.items():
        out[kind] = {name: obj.model_dump(by_alias=True) for name, obj in bucket.items()}
    return out


def _seat():
    return _defs()["Seat"]["seat_sourcing_poc"]


def _limits():
    return (_seat().get("spec") or {}).get("limits") or {}


class TaskContractTests(unittest.TestCase):
    def _build(self, template: dict, *, person_id: str | None = None, role: str = "requester"):
        return contracts.build_task_contract(
            packs_dir=PACKS_DIR,
            pack_name="procurement_demo",
            pack_version=1,
            pack_digest="test",
            defs=_defs(),
            org_id="org_demo",
            instance_id="QQ-T01",
            task_id="task_test_1",
            seat_name="seat_sourcing_poc",
            seat_version=1,
            seat_doc=_seat(),
            workflow_name="quick_quote",
            template=template,
            participant_role=role,
            person_id=person_id,
            seat_limits=_limits(),
            org=ORG,
        )

    def test_request_intake_ceiling_internal_without_org(self) -> None:
        c = contracts.build_task_contract(
            packs_dir=PACKS_DIR,
            pack_name="procurement_demo",
            pack_version=1,
            pack_digest="test",
            defs=_defs(),
            org_id="org_demo",
            instance_id="QQ-T01",
            task_id="task_test_1",
            seat_name="seat_sourcing_poc",
            seat_version=1,
            seat_doc=_seat(),
            workflow_name="quick_quote",
            template={
                "template": "request_intake",
                "skill": "request_intake",
                "work_type": "analysis",
                "on_behalf_of": "requester",
            },
            participant_role="requester",
            person_id="faisal",
            seat_limits=_limits(),
        )
        ceiling = c["permission_scope"]["classification_ceiling"]
        self.assertEqual(ceiling, "internal")

    def test_supplier_lookup_ceiling_shareable(self) -> None:
        c = self._build(
            {
                "template": "supplier_lookup",
                "skill": "supplier_lookup",
                "work_type": "analysis",
                "on_behalf_of": "buyer",
            },
            person_id="noura",
            role="buyer",
        )
        self.assertEqual(c["permission_scope"]["classification_ceiling"], "shareable")

    def test_requester_bound_never_above_clearance(self) -> None:
        c = self._build(
            {
                "template": "request_intake",
                "skill": "request_intake",
                "work_type": "analysis",
                "on_behalf_of": "requester",
            },
            person_id="faisal",
            role="requester",
        )
        self.assertEqual(c["permission_scope"]["classification_ceiling"], "shareable")

    def test_supplier_lookup_unbound_buyer_uses_queue_clearance(self) -> None:
        c = self._build(
            {
                "template": "supplier_lookup",
                "skill": "supplier_lookup",
                "work_type": "analysis",
                "on_behalf_of": "buyer",
            },
            person_id=None,
            role="buyer",
        )
        self.assertEqual(c["permission_scope"]["classification_ceiling"], "shareable")

    def test_rfq_draft_no_send_message_rfq_send_has_it(self) -> None:
        draft = self._build(
            {
                "template": "rfq_draft",
                "skill": "rfq_authoring",
                "work_type": "document_draft",
                "on_behalf_of": "buyer",
            },
            person_id="noura",
            role="buyer",
        )
        send = self._build(
            {
                "template": "rfq_send",
                "skill": "rfq_authoring",
                "work_type": "outbound_communication",
                "on_behalf_of": "buyer",
                "budget": {
                    "tokens": 20000,
                    "cost_usd": 0.5,
                    "seconds": 300,
                    "steps": 6,
                    "actions": 10,
                    "retries": 2,
                },
            },
            person_id="noura",
            role="buyer",
        )
        draft_tools = {t["name"] for t in draft["allowed_tools"]}
        send_tools = {t["name"] for t in send["allowed_tools"]}
        self.assertNotIn("send_message", draft_tools)
        self.assertIn("send_message", send_tools)

    def test_budget_template_override_and_seat_cap(self) -> None:
        send = self._build(
            {
                "template": "rfq_send",
                "skill": "rfq_authoring",
                "work_type": "outbound_communication",
                "on_behalf_of": "buyer",
                "budget": {
                    "tokens": 20000,
                    "cost_usd": 0.5,
                    "seconds": 300,
                    "steps": 6,
                    "actions": 10,
                    "retries": 2,
                },
            },
            person_id="noura",
            role="buyer",
        )
        self.assertEqual(send["budget"]["steps"], 6)
        self.assertEqual(send["budget"]["tokens"], 20000)
        skill_only = self._build(
            {
                "template": "supplier_lookup",
                "skill": "supplier_lookup",
                "work_type": "analysis",
                "on_behalf_of": "buyer",
            },
            person_id="noura",
            role="buyer",
        )
        self.assertEqual(skill_only["budget"]["steps"], 10)


class TaskContractValidationTests(unittest.TestCase):
    def test_template_without_on_behalf_of_fails(self) -> None:
        from aos.registry import validate_pack

        org = yaml.safe_load((REPO / "seed" / "org.yaml").read_text())
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        pack = tmp / "pack"
        shutil.copytree(PACK, pack)
        wf = pack / "workflows" / "quick_quote.yaml"
        doc = parse_yaml(wf.read_text())
        task = doc["spec"]["states"]["intake"]["tasks"][0]
        if isinstance(task, dict):
            task.pop("on_behalf_of", None)
        else:
            self.fail("expected task template dict")
        wf.write_text(yaml.safe_dump(doc, sort_keys=False))
        report = validate_pack(pack, org=org)
        self.assertFalse(report.ok)
        self.assertIn("E_ON_BEHALF_OF", report.codes())

    def test_skill_budget_above_seat_fails(self) -> None:
        from aos.registry import validate_pack

        org = yaml.safe_load((REPO / "seed" / "org.yaml").read_text())
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        pack = tmp / "pack"
        shutil.copytree(PACK, pack)
        sk = pack / "skills" / "request_intake" / "skill.yaml"
        doc = parse_yaml(sk.read_text())
        doc["spec"]["budget"]["tokens"] = 999999
        sk.write_text(yaml.safe_dump(doc, sort_keys=False))
        report = validate_pack(pack, org=org)
        self.assertFalse(report.ok)
        self.assertIn("E_BUDGET_SEAT", report.codes())


if __name__ == "__main__":
    unittest.main()
