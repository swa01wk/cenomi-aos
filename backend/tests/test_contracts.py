"""The contracts in docs/specs/contracts stay valid and consistent with the code.

- every JSON Schema is valid Draft 2020-12, and every example validates against its schema;
- openapi.yaml parses, every $ref resolves (internal and into schemas/*.json), operation IDs are unique and every
  operation names its milestone;
- every operation marked M0 exists in the FastAPI app, and every route the app serves is in the OpenAPI document.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "docs" / "specs" / "contracts"
SCHEMAS = CONTRACTS / "schemas"
EXAMPLES = CONTRACTS / "examples"
METHODS = {"get", "post", "put", "patch", "delete"}
MILESTONES = {"M0", "M1", "M2", "M3", "M4", "M5"}


def _schemas() -> dict[str, dict]:
    return {p.name: json.loads(p.read_text()) for p in sorted(SCHEMAS.glob("*.schema.json"))}


def _registry() -> Registry:
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in _schemas().values())


def _pointer(doc, pointer: str):
    node = doc
    for part in [p for p in pointer.lstrip("/").split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _refs(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                found.append(v)
            else:
                _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)
    return found


class SchemaTests(unittest.TestCase):
    def test_schemas_are_valid_2020_12(self) -> None:
        schemas = _schemas()
        self.assertGreaterEqual(len(schemas), 6)
        for name, schema in schemas.items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)
                self.assertTrue(schema["$id"].endswith(name))

    def test_examples_validate(self) -> None:
        schemas, registry = _schemas(), _registry()
        pairs = {
            "task-contract.rfq_draft.json": "task-contract.schema.json",
            "context-envelope.rfq_draft.json": "context-envelope.schema.json",
            "agent-result.rfq_draft.json": "agent-result.schema.json",
            "execution-event.tool_denied.json": "execution-event.schema.json",
            "problem.stale_version.json": "problem.schema.json",
        }
        for example, schema_name in pairs.items():
            with self.subTest(example=example):
                Draft202012Validator(schemas[schema_name], registry=registry).validate(json.loads((EXAMPLES / example).read_text()))
        ui = Draft202012Validator(schemas["ui-event.schema.json"], registry=registry)
        for event in json.loads((EXAMPLES / "ui-events.json").read_text()):
            with self.subTest(ui_event=event["type"]):
                ui.validate(event)

    def test_bad_examples_are_rejected(self) -> None:
        schemas, registry = _schemas(), _registry()
        result = json.loads((EXAMPLES / "agent-result.rfq_draft.json").read_text())
        result["proposed_graph_changes"] = [{"add": "task"}]          # ADR 010: no graph mutation in the POC
        self.assertFalse(Draft202012Validator(schemas["agent-result.schema.json"], registry=registry).is_valid(result))
        failed = dict(json.loads((EXAMPLES / "agent-result.rfq_draft.json").read_text()), status="failed")
        self.assertFalse(Draft202012Validator(schemas["agent-result.schema.json"], registry=registry).is_valid(failed))
        envelope = json.loads((EXAMPLES / "context-envelope.rfq_draft.json").read_text())
        envelope["secret"] = "x"
        self.assertFalse(Draft202012Validator(schemas["context-envelope.schema.json"], registry=registry).is_valid(envelope))


class OpenApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text())

    def operations(self):
        for path, item in self.doc["paths"].items():
            for method, op in item.items():
                if method in METHODS:
                    yield path, method, op

    def test_every_ref_resolves(self) -> None:
        for ref in sorted(set(_refs(self.doc))):
            with self.subTest(ref=ref):
                file, _, pointer = ref.partition("#")
                target = self.doc if not file else json.loads((CONTRACTS / file).read_text())
                self.assertIsNotNone(_pointer(target, pointer))

    def test_operations_are_complete(self) -> None:
        ids, tags = set(), {t["name"] for t in self.doc["tags"]}
        for path, method, op in self.operations():
            with self.subTest(op=f"{method.upper()} {path}"):
                self.assertNotIn(op["operationId"], ids)
                ids.add(op["operationId"])
                self.assertIn(op["x-milestone"], MILESTONES)
                self.assertTrue(set(op["tags"]) <= tags)
                self.assertIn("responses", op)
        self.assertGreater(len(ids), 60)

    def test_component_schemas_are_valid(self) -> None:
        for name, schema in self.doc["components"]["schemas"].items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)

    def test_m0_operations_match_the_running_app(self) -> None:
        try:
            from aos.api import create_app
            from aos.kernel.settings import Settings
        except ImportError as exc:  # FastAPI not installed in this environment
            self.skipTest(f"FastAPI unavailable: {exc}")
        app = create_app(Settings.from_env(seed_on_start=False))
        served = {(m, p.removeprefix("/api")) for p, item in app.openapi()["paths"].items() if p.startswith("/api")
                  for m in item if m in METHODS}
        spec_m0 = {(m, p) for p, m, op in self.operations() if op["x-milestone"] == "M0"}
        spec_all = {(m, p) for p, m, _ in self.operations()}
        self.assertEqual(spec_m0 - served, set(), "M0 operations in the spec but not served")
        self.assertEqual(served - spec_all, set(), "served routes missing from the spec")

    def test_m1_publish_operations_match_the_running_app(self) -> None:
        try:
            from aos.api import create_app
            from aos.kernel.settings import Settings
        except ImportError as exc:
            self.skipTest(f"FastAPI unavailable: {exc}")
        app = create_app(Settings.from_env(seed_on_start=False))
        served = {(m, p.removeprefix("/api")) for p, item in app.openapi()["paths"].items() if p.startswith("/api")
                  for m in item if m in METHODS}
        m1_publish = {
            ("post", "/console/pack-versions/{version_id}/publish-requests"),
            ("get", "/console/publish-requests"),
            ("post", "/console/publish-requests/{id}/approve"),
            ("post", "/console/publish-requests/{id}/reject"),
        }
        self.assertTrue(m1_publish <= served, f"M1 publish routes missing from app: {m1_publish - served}")

    def test_m1_seat_operations_match_the_running_app(self) -> None:
        try:
            from aos.api import create_app
            from aos.kernel.settings import Settings
        except ImportError as exc:
            self.skipTest(f"FastAPI unavailable: {exc}")
        app = create_app(Settings.from_env(seed_on_start=False))
        served = {(m, p.removeprefix("/api")) for p, item in app.openapi()["paths"].items() if p.startswith("/api")
                  for m in item if m in METHODS}
        m1_seats = {
            ("get", "/console/seats"),
            ("get", "/console/seats/{seat}"),
            ("post", "/console/seats/{seat}/configure"),
            ("post", "/console/seats/{seat}/approve"),
            ("post", "/console/seats/{seat}/activate"),
        }
        self.assertTrue(m1_seats <= served, f"M1 seat routes missing from app: {m1_seats - served}")

    def test_m1_instance_commands_match_the_running_app(self) -> None:
        try:
            from aos.api import create_app
            from aos.kernel.settings import Settings
        except ImportError as exc:
            self.skipTest(f"FastAPI unavailable: {exc}")
        app = create_app(Settings.from_env(seed_on_start=False))
        served = {(m, p.removeprefix("/api")) for p, item in app.openapi()["paths"].items() if p.startswith("/api")
                  for m in item if m in METHODS}
        m1_instances = {
            ("get", "/workspace/digital-workers"),
            ("get", "/instances"),
            ("post", "/instances"),
            ("get", "/instances/{id}"),
            ("get", "/instances/{id}/turns"),
            ("post", "/instances/{id}/turns"),
            ("get", "/instances/{id}/events"),
        }
        self.assertTrue(m1_instances <= served, f"M1 instance routes missing: {m1_instances - served}")

    def test_m1_worker_core_operations_match_the_running_app(self) -> None:
        try:
            from aos.api import create_app
            from aos.kernel.settings import Settings
        except ImportError as exc:
            self.skipTest(f"FastAPI unavailable: {exc}")
        app = create_app(Settings.from_env(seed_on_start=False))
        served = {(m, p.removeprefix("/api")) for p, item in app.openapi()["paths"].items() if p.startswith("/api")
                  for m in item if m in METHODS}
        m1_worker_a = {
            ("post", "/worker/attempts/claim"),
            ("post", "/worker/attempts/{id}/heartbeat"),
            ("get", "/worker/attempts/{id}/contract"),
            ("post", "/worker/attempts/{id}/context"),
            ("post", "/worker/attempts/{id}/tools/{tool}"),
            ("post", "/worker/attempts/{id}/fail"),
        }
        self.assertTrue(m1_worker_a <= served, f"M1 worker routes missing: {m1_worker_a - served}")


if __name__ == "__main__":
    unittest.main()
