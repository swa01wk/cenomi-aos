"""Task contracts per Skill run (M2-AG-01): ceilings, effect grants, budgets, and the validation behind them."""

from __future__ import annotations

import unittest
from pathlib import Path

from aos.kernel import contracts
from aos.registry.loader import load_pack

from .test_validate import PACK, PackCase

SEAT = "seat_sourcing_poc"


def _defs() -> tuple[dict[str, dict[str, dict]], str]:
    pack = load_pack(PACK)
    defs = {
        kind: {name: obj.model_dump(mode="json", by_alias=True) for name, obj in objs.items()}
        for kind, objs in pack.objects.items()
    }
    return defs, pack.digest


def _templates(defs: dict[str, dict[str, dict]]) -> dict[str, dict]:
    spec = defs["WorkflowDefinition"]["quick_quote"]["spec"]
    out: dict[str, dict] = {}
    for st in spec["states"].values():
        for t in st.get("tasks") or []:
            out[t["template"]] = t
        for t in (st.get("on_event") or {}).values():
            out[t["template"]] = t
    for region in spec.get("parallel") or []:
        out[region["start"]["template"]] = region["start"]
    return out


class TaskContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.defs, cls.digest = _defs()
        cls.templates = _templates(cls.defs)

    def contract(self, template: str) -> dict:
        tpl = self.templates[template]
        seat_doc = self.defs["Seat"][SEAT]
        return contracts.build_task_contract(
            packs_dir=PACK.parent,
            pack_name="procurement_demo",
            pack_version=2,
            pack_digest=self.digest,
            defs=self.defs,
            org_id="org_demo",
            instance_id="QQ-TEST",
            task_id="task_test",
            seat_name=SEAT,
            seat_version=1,
            seat_doc=seat_doc,
            workflow_name="quick_quote",
            template=tpl,
            participant_role=tpl["on_behalf_of"],
            person_id=None,
            seat_limits=seat_doc["spec"]["limits"],
        )

    def tools(self, template: str) -> list[str]:
        return [g["name"] for g in self.contract(template)["allowed_tools"]]

    def test_ceiling_comes_from_the_skill_run(self) -> None:
        self.assertEqual(self.contract("supplier_lookup")["permission_scope"]["classification_ceiling"], "shareable")
        self.assertEqual(self.contract("request_intake")["permission_scope"]["classification_ceiling"], "internal")
        self.assertEqual(self.contract("rfq_draft")["permission_scope"]["classification_ceiling"], "shareable")
        self.assertEqual(self.contract("quote_comparison")["permission_scope"]["classification_ceiling"], "restricted")

    def test_ceiling_never_above_the_on_behalf_of_role(self) -> None:
        self.assertEqual(contracts.role_clearance(self.defs, "requester"), "internal")
        defs = {**self.defs, "Skill": dict(self.defs["Skill"])}
        skill = dict(defs["Skill"]["request_intake"])
        spec = dict(skill["spec"])
        spec["runs"] = {"analysis": {"classification_ceiling": "restricted", "budget": None}}
        skill["spec"] = spec
        defs["Skill"]["request_intake"] = skill
        seat_doc = defs["Seat"][SEAT]
        contract = contracts.build_task_contract(
            packs_dir=PACK.parent,
            pack_name="procurement_demo",
            pack_version=2,
            pack_digest=self.digest,
            defs=defs,
            org_id="org_demo",
            instance_id="QQ-TEST",
            task_id="task_test",
            seat_name=SEAT,
            seat_version=1,
            seat_doc=seat_doc,
            workflow_name="quick_quote",
            template=self.templates["request_intake"],
            participant_role="requester",
            person_id=None,
            seat_limits=seat_doc["spec"]["limits"],
        )
        self.assertEqual(contract["permission_scope"]["classification_ceiling"], "internal")

    def test_committed_effects_only_for_effect_work_types(self) -> None:
        self.assertNotIn("send_message", self.tools("rfq_draft"))
        self.assertIn("send_message", self.tools("rfq_send"))
        self.assertNotIn("create_po", self.tools("quote_comparison"))
        self.assertIn("create_po", self.tools("po_create"))

    def test_each_tool_is_granted_once(self) -> None:
        for template in self.templates:
            names = self.tools(template)
            self.assertEqual(len(names), len(set(names)), template)

    def test_budget_comes_from_the_skill_run(self) -> None:
        intake = self.contract("request_intake")["budget"]
        self.assertEqual(
            (intake["tokens"], intake["cost_usd"], intake["time_s"], intake["steps"], intake["actions"]),
            (40000, 1.0, 300, 8, 6),
        )
        self.assertEqual(contracts.max_attempts_from_budget(intake), 4)
        self.assertEqual(self.contract("rfq_draft")["budget"]["steps"], 12)
        self.assertEqual(self.contract("rfq_send")["budget"]["steps"], 6)

    def test_run_without_budget_uses_the_seat_attempt_limits(self) -> None:
        limits = self.defs["Seat"][SEAT]["spec"]["limits"]
        self.assertEqual(contracts.run_budget_block(None, limits), contracts.seat_budget_block(limits))


class TaskTemplateValidationTests(PackCase):
    def test_template_without_on_behalf_of_fails(self) -> None:
        def fn(d):
            del d["spec"]["states"]["rfq_drafting"]["tasks"][0]["on_behalf_of"]

        self.edit("workflows/quick_quote.yaml", fn)
        self.assertFailsWith("E_ON_BEHALF_OF")

    def test_on_event_and_parallel_templates_need_on_behalf_of(self) -> None:
        def fn(d):
            del d["spec"]["states"]["awaiting_quotes"]["on_event"]["mail.message_received"]["on_behalf_of"]
            del d["spec"]["parallel"][0]["start"]["on_behalf_of"]

        self.edit("workflows/quick_quote.yaml", fn)
        report = self._report()
        paths = {i.path for i in report.issues if i.code == "E_ON_BEHALF_OF"}
        self.assertEqual(
            paths,
            {
                "spec.states.awaiting_quotes.on_event.mail.message_received.on_behalf_of",
                "spec.parallel[0].start.on_behalf_of",
            },
        )

    def test_run_for_a_work_type_the_skill_lacks_fails(self) -> None:
        def fn(d):
            d["spec"]["runs"]["record_update"] = {"classification_ceiling": "internal"}

        self.edit("skills/request_intake/skill.yaml", fn)
        self.assertFailsWith("E_SKILL_RUN")

    def test_run_budget_over_the_seat_run_limits_fails(self) -> None:
        def fn(d):
            d["spec"]["runs"]["analysis"]["budget"]["actions"] = 50

        self.edit("skills/request_intake/skill.yaml", fn)
        self.assertFailsWith("E_SKILL_BUDGET")

    def _report(self):
        from aos.registry import validate_pack

        from .test_validate import ORG

        return validate_pack(Path(self.pack), org=ORG)


if __name__ == "__main__":
    unittest.main()
