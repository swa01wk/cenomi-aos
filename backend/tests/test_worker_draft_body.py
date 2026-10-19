"""save_draft is an update: the worker merges the model's fields onto the draft's current content."""

from __future__ import annotations

import unittest

from aos.kernel.command_schemas import enrich_command_schema
from aos.worker.draft_body import build_save_draft_body, merge_draft_content

CONTRACT = {"expected_outputs": [{"artifact_type": "doc"}]}


def _envelope(content: dict | None, redactions: list | None = None) -> dict:
    arts = [] if content is None else [{"artifact_id": "art_1", "artifact_type": "doc", "version": 1, "content": content}]
    return {"artifacts": arts, "redactions": redactions or []}


class DraftMergeTests(unittest.TestCase):
    def test_fields_left_out_or_blank_are_kept(self) -> None:
        # A model filling every schema field sends null or "" for the ones it isn't touching; those keep their value.
        self.assertEqual(
            merge_draft_content({"a": 1, "b": "x", "c": True, "cat": "C1"}, {"b": "y", "c": None, "cat": " ", "d": 2}),
            {"a": 1, "b": "y", "c": True, "cat": "C1", "d": 2},
        )

    def test_first_save_is_the_content_as_sent(self) -> None:
        body = build_save_draft_body(
            contract=CONTRACT, envelope=_envelope(None), model_args={"content": {"a": 1, "b": None}}, saved_in_attempt={}
        )
        self.assertEqual(body["content"], {"a": 1})
        self.assertNotIn("artifact_id", body)

    def test_update_keeps_the_current_version_fields(self) -> None:
        body = build_save_draft_body(
            contract=CONTRACT,
            envelope=_envelope({"title": "T", "category": "C1"}),
            model_args={"content": {"quantity": 40}},
            saved_in_attempt={},
        )
        self.assertEqual(body["content"], {"title": "T", "category": "C1", "quantity": 40})
        self.assertEqual((body["artifact_id"], body["base_version"]), ("art_1", 1))

    def test_a_save_earlier_in_the_attempt_is_the_base(self) -> None:
        body = build_save_draft_body(
            contract=CONTRACT,
            envelope=_envelope({"title": "T"}),
            model_args={"content": {"site": "S"}},
            saved_in_attempt={"doc": {"artifact_id": "art_1", "version": 2, "content": {"title": "T", "qty": 4}}},
        )
        self.assertEqual(body["content"], {"title": "T", "qty": 4, "site": "S"})
        self.assertEqual(body["base_version"], 2)

    def test_redacted_draft_is_not_merged(self) -> None:
        # The envelope hides a field, so its content isn't the whole draft: save what the model sent.
        body = build_save_draft_body(
            contract=CONTRACT,
            envelope=_envelope({"title": "T"}, redactions=[{"artifact_type": "doc", "field": "secret", "reason": "r"}]),
            model_args={"content": {"site": "S"}},
            saved_in_attempt={},
        )
        self.assertEqual(body["content"], {"site": "S"})


class KernelCommandDescriptionTests(unittest.TestCase):
    def test_ask_question_says_it_ends_the_reply(self) -> None:
        entry = enrich_command_schema("ask_question", {}, {}, {"name": "ask_question", "input_schema": {}})
        self.assertIn("end this reply", entry["description"])


if __name__ == "__main__":
    unittest.main()
