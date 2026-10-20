"""Pure workflow transition matching (M2-BE-01 part 1)."""

from __future__ import annotations

import unittest
from pathlib import Path

from aos.kernel.workflow import match_transition
from aos.registry.kinds import WorkflowDefinition
from aos.registry.loader import load_pack

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "packs" / "procurement_demo"


def _quick_quote() -> WorkflowDefinition:
    wf = load_pack(PACK).get("WorkflowDefinition")["quick_quote"]
    assert isinstance(wf, WorkflowDefinition)
    return wf


class QuickQuoteTransitions(unittest.TestCase):
    def setUp(self) -> None:
        self.wf = _quick_quote()

    def test_brief_confirmed(self) -> None:
        m = match_transition(
            self.wf,
            state="intake",
            event="decision.brief_confirmed",
            actor_role="requester",
        )
        self.assertIsNone(m.reason)
        assert m.transition is not None
        self.assertEqual(m.transition.to, "shortlisting")
        self.assertEqual(m.entry_tasks, [])

    def test_wrong_role(self) -> None:
        m = match_transition(
            self.wf,
            state="intake",
            event="decision.brief_confirmed",
            actor_role="buyer",
        )
        self.assertIsNone(m.transition)
        self.assertEqual(m.reason, "wrong_role")

    def test_shortlist_guard_pass_and_fail(self) -> None:
        ok = match_transition(
            self.wf,
            state="shortlisting",
            event="decision.shortlist_confirmed",
            actor_role="buyer",
            attributes={"shortlist_count": 3},
        )
        self.assertIsNone(ok.reason)
        assert ok.transition is not None
        self.assertEqual(ok.transition.to, "rfq_drafting")
        self.assertEqual(len(ok.entry_tasks), 1)
        self.assertEqual(ok.entry_tasks[0].template, "rfq_draft")

        bad = match_transition(
            self.wf,
            state="shortlisting",
            event="decision.shortlist_confirmed",
            actor_role="buyer",
            attributes={"shortlist_count": 2},
        )
        self.assertIsNone(bad.transition)
        self.assertEqual(bad.reason, "guard_failed")

    def test_task_completed_without_by(self) -> None:
        m = match_transition(
            self.wf,
            state="rfq_drafting",
            event="task.completed.rfq_draft",
            actor_role=None,
        )
        self.assertIsNone(m.reason)
        assert m.transition is not None
        self.assertEqual(m.transition.to, "rfq_sending")

    def test_effects_on_send_and_close(self) -> None:
        m = match_transition(
            self.wf,
            state="rfq_sending",
            event="task.completed.rfq_send",
            actor_role=None,
        )
        assert m.transition is not None
        self.assertEqual(m.effects, [{"start_timer": "quote_deadline"}])

        m2 = match_transition(
            self.wf,
            state="ordering",
            event="task.completed.po_create",
            actor_role=None,
        )
        assert m2.transition is not None
        self.assertEqual(m2.transition.to, "closed")
        self.assertIn({"handover": "requester"}, m2.effects)

    def test_list_on_events(self) -> None:
        attrs = {"quote_count": 2}
        for ev in ("timer.quotes_closed", "event.all_quotes_received"):
            m = match_transition(
                self.wf,
                state="awaiting_quotes",
                event=ev,
                actor_role=None,
                attributes=attrs,
            )
            self.assertIsNone(m.reason, ev)
            assert m.transition is not None
            self.assertEqual(m.transition.to, "comparison", ev)

    def test_every_transition_has_a_firing_event(self) -> None:
        cases = [
            ("intake", "decision.brief_confirmed", "requester", {}),
            ("shortlisting", "decision.shortlist_confirmed", "buyer", {"shortlist_count": 3}),
            ("rfq_drafting", "task.completed.rfq_draft", None, {}),
            ("rfq_sending", "task.completed.rfq_send", None, {}),
            ("awaiting_quotes", "timer.quotes_closed", None, {"quote_count": 2}),
            ("comparison", "decision.supplier_selected", "buyer", {}),
            ("ordering", "task.completed.po_create", None, {}),
        ]
        for state, event, role, attrs in cases:
            m = match_transition(
                self.wf,
                state=state,
                event=event,
                actor_role=role,
                attributes=attrs,
            )
            self.assertIsNone(m.reason, f"{state} {event}")
            self.assertIsNotNone(m.transition, f"{state} {event}")


if __name__ == "__main__":
    unittest.main()
