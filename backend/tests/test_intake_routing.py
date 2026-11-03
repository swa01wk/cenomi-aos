"""Pack-neutral intake routing from workflow hints."""

from __future__ import annotations

import unittest

from aos.kernel.intake_routing import route_intake_message


class IntakeRoutingTests(unittest.TestCase):
    def test_picks_workflow_with_stronger_hint_match(self) -> None:
        workers = [
            {
                "seat": "seat_a",
                "workflows": [
                    {"name": "wf_alpha", "intake_hints": ["laptop", "hardware"]},
                    {"name": "wf_beta", "intake_hints": ["leave", "hr"]},
                ],
            },
            {
                "seat": "seat_b",
                "workflows": [{"name": "wf_other", "intake_hints": ["travel"]}],
            },
        ]
        seat, wf = route_intake_message("Need 20 laptops for the mall", workers)
        self.assertEqual(seat, "seat_a")
        self.assertEqual(wf, "wf_alpha")

    def test_title_tokens_add_to_score(self) -> None:
        workers = [
            {
                "seat": "seat_a",
                "workflows": [
                    {
                        "name": "wf_alpha",
                        "title": "Equipment request",
                        "description": "Office gear",
                        "intake_hints": ["equipment"],
                    },
                ],
            },
        ]
        seat, wf = route_intake_message("We need new equipment for the site", workers)
        self.assertEqual((seat, wf), ("seat_a", "wf_alpha"))

    def test_skips_coordination_workflows_without_hints(self) -> None:
        workers = [
            {
                "seat": "seat_coord",
                "workflows": [{"name": "coord", "intake_hints": []}],
            },
            {
                "seat": "seat_spec",
                "workflows": [{"name": "qq", "intake_hints": ["equipment", "need"]}],
            },
        ]
        seat, wf = route_intake_message("We need equipment for the site", workers)
        self.assertEqual((seat, wf), ("seat_spec", "qq"))

    def test_rfp_hints_beat_generic_equipment(self) -> None:
        workers = [
            {
                "seat": "seat_sourcing_poc",
                "workflows": [
                    {"name": "quick_quote", "intake_hints": ["equipment", "quote", "laptop"]},
                    {
                        "name": "sourcing_rfp",
                        "title": "Sourcing event (full RFP)",
                        "intake_hints": ["rfp", "web service", "website", "software"],
                    },
                ],
            },
        ]
        seat, wf = route_intake_message(
            "We need a vendor to build a customer web service and API for our portal",
            workers,
        )
        self.assertEqual(seat, "seat_sourcing_poc")
        self.assertEqual(wf, "sourcing_rfp")

    def test_web_portal_message_prefers_sourcing_rfp_over_quick_quote_service_hint(self) -> None:
        workers = [
            {
                "seat": "seat_sourcing_poc",
                "workflows": [
                    {"name": "quick_quote", "intake_hints": ["equipment", "quote", "service", "need"]},
                    {
                        "name": "sourcing_rfp",
                        "title": "Sourcing event (full RFP)",
                        "intake_hints": ["rfp", "web service", "portal", "api"],
                    },
                ],
            },
        ]
        seat, wf = route_intake_message(
            "Customer-facing web portal and REST API for mall tenants and operations",
            workers,
        )
        self.assertEqual(wf, "sourcing_rfp")

    def test_website_rfp_phrasing_routes_to_sourcing_rfp(self) -> None:
        workers = [
            {
                "seat": "seat_sourcing_poc",
                "workflows": [
                    {"name": "quick_quote", "intake_hints": ["need", "service", "buy", "quote"]},
                    {
                        "name": "sourcing_rfp",
                        "title": "Sourcing event (full RFP)",
                        "intake_hints": ["rfp", "website", "software", "development"],
                    },
                ],
            },
        ]
        seat, wf = route_intake_message(
            "I need to create an RFP for website redesign",
            workers,
        )
        self.assertEqual(seat, "seat_sourcing_poc")
        self.assertEqual(wf, "sourcing_rfp")

    def test_defaults_to_first_when_no_hints_match(self) -> None:
        workers = [
            {
                "seat": "seat_only",
                "workflows": [{"name": "wf_one", "intake_hints": ["zzzz"]}],
            },
        ]
        seat, wf = route_intake_message("hello there", workers)
        self.assertEqual((seat, wf), ("seat_only", "wf_one"))


if __name__ == "__main__":
    unittest.main()
