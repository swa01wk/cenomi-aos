"""Inbound mail dedupe and trigger context for quote_triage."""

from __future__ import annotations

import unittest

from aos.kernel import inbound_mail


class InboundMailTests(unittest.TestCase):
    def test_parse_instance_ref(self) -> None:
        inst, sup = inbound_mail.parse_instance_ref("QQ-0019:SUP-11632")
        self.assertEqual(inst, "QQ-0019")
        self.assertEqual(sup, "SUP-11632")

    def test_trigger_context_from_payload(self) -> None:
        payload = {
            "ref": "QQ-0019:SUP-11632",
            "conversation_id": "conv-abc",
            "message_id": "msg-1",
            "sender": "quotes+SUP-11632@vendor.example",
        }
        ctx = inbound_mail.trigger_context_from_payload(event="mail.message_received", payload=payload)
        self.assertEqual(ctx["conversation_id"], "conv-abc")
        self.assertEqual(ctx["supplier_id"], "SUP-11632")
        self.assertEqual(ctx["message_id"], "msg-1")


    def test_build_task_contract_carries_trigger_context(self) -> None:
        from aos.kernel.contracts import build_task_contract
        from aos.registry.loader import load_pack
        from aos.kernel.settings import REPO

        pack_root = REPO / "packs" / "procurement_demo"
        loaded = load_pack(pack_root)
        defs = loaded.objects
        pack = loaded.manifest
        assert pack is not None
        seat = defs["Seat"]["seat_sourcing_poc"]
        trigger = {
            "event": "mail.message_received",
            "conversation_id": "conv-test",
            "message_id": "msg-test",
            "supplier_id": "SUP-1",
            "ref": "QQ-0001:SUP-1",
        }
        contract = build_task_contract(
            packs_dir=REPO / "packs",
            pack_name="procurement_demo",
            pack_version=int(pack.metadata.version),
            pack_digest=loaded.digest,
            defs={k: {n: v.model_dump() for n, v in o.items()} for k, o in defs.items()},
            org_id="org_demo",
            instance_id="QQ-0001",
            task_id="task_test",
            seat_name="seat_sourcing_poc",
            seat_version=1,
            seat_doc=seat.model_dump(),
            workflow_name="quick_quote",
            template={
                "template": "quote_triage",
                "skill": "quote_triage",
                "work_type": "analysis",
                "on_behalf_of": "buyer",
            },
            participant_role="buyer",
            person_id="noura",
            seat_limits=(seat.spec.limits.model_dump() if hasattr(seat.spec.limits, "model_dump") else seat.spec.limits),
            trigger_context=trigger,
        )
        self.assertEqual(contract.get("trigger_context"), trigger)


if __name__ == "__main__":
    unittest.main()
