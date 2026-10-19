"""Snapshot stages follow the workflow's flow, not jsonb key order."""

from __future__ import annotations

import unittest

from aos.kernel.instances import _stages, _state_order

# Keys deliberately in jsonb order (shorter keys first), not flow order.
SPEC = {
    "initial": "start",
    "states": {"done": {"label": "Done"}, "start": {"label": "Start"}, "review": {"label": "Review"},
               "drafting": {"label": "Drafting"}, "side_path": {"label": "Side path"}},
    "transitions": [
        {"from": "start", "to": "drafting"},
        {"from": "drafting", "to": "review"},
        {"from": ["review"], "to": "done"},
        {"from": "review", "to": "drafting"},
    ],
}


class StageOrderTests(unittest.TestCase):
    def test_flow_order_from_initial(self) -> None:
        self.assertEqual(_state_order(SPEC), ["start", "drafting", "review", "done", "side_path"])

    def test_statuses_follow_flow_order(self) -> None:
        stages = _stages({"spec": SPEC}, "start")
        self.assertEqual([s["state"] for s in stages], ["start", "drafting", "review", "done", "side_path"])
        self.assertEqual([s["status"] for s in stages], ["current", "next", "next", "next", "next"])
        self.assertEqual(stages[0]["label"], "Start")

    def test_done_before_current(self) -> None:
        stages = _stages({"spec": SPEC}, "review")
        self.assertEqual([s["status"] for s in stages][:4], ["done", "done", "current", "next"])


if __name__ == "__main__":
    unittest.main()
