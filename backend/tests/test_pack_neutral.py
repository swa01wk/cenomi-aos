"""Platform code must not know the example pack.

The kernel, API, gateway, worker, registry and the web app are pack-neutral: domain names, stages, fields and
policies reach them as data from a pack. This test fails if a name from any pack (the pack itself, its workflows,
Seats, Skills, artifact types, connectors, verifiers) or a domain word appears in platform code.

Domain code that a pack points to by `implementation:` (deterministic tools in `aos/tools`, verifiers in
`aos/verifiers`) and the mock connectors (`aos/connectors`) are pack extensions and are not scanned. Fake-model
scripts (`worker/scripts/*.yaml`) are test data and are not scanned either.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from aos.registry.loader import load_pack

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = [ROOT / "backend/src/aos" / d for d in ("kernel", "api", "gateway", "worker", "registry")] + [
    ROOT / "backend/src/aos/cli.py", ROOT / "backend/src/aos/sse.py", ROOT / "web/src"]
SUFFIXES = {".py", ".ts", ".tsx", ".css", ".sql", ".jinja"}
NAMED_KINDS = ("WorkflowDefinition", "Seat", "Skill", "ArtifactType", "ToolProvider", "Verifier", "Policy")
# Words from the example domain that a generic screen or kernel module has no reason to use.
DOMAIN_WORDS = {"procurement", "quote", "quotes", "rfq", "supplier", "suppliers", "sourcing", "vendor", "vendors"}
# Generic words that happen to be names in a pack; using them is fine.
ALLOWED = {"brief", "intake", "comparison", "mailbox"}


def _terms() -> set[str]:
    terms = set(DOMAIN_WORDS)
    for pack in sorted((ROOT / "packs").iterdir()):
        if not (pack / "pack.yaml").exists():
            continue
        loaded = load_pack(pack)
        terms.add(pack.name)
        for kind in NAMED_KINDS:
            terms.update(loaded.get(kind))
    return {t.lower() for t in terms} - ALLOWED


def _files():
    for base in PLATFORM:
        paths = [base] if base.is_file() else base.rglob("*")
        for p in paths:
            if p.suffix in SUFFIXES and "__pycache__" not in p.parts and "/scripts/" not in p.as_posix():
                # OpenAPI examples and @description strings; not hand-written UI code.
                if p.name == "schema.d.ts":
                    continue
                yield p


class PackNeutralTest(unittest.TestCase):
    def test_platform_code_does_not_name_the_pack(self) -> None:
        terms = _terms()
        self.assertIn("quick_quote", terms)  # the scan really reads the pack
        pattern = re.compile(r"(?<![a-z0-9_])(" + "|".join(sorted(map(re.escape, terms), key=len, reverse=True))
                             + r")(?![a-z0-9_])", re.I)
        hits = []
        for p in _files():
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                m = pattern.search(line)
                if m:
                    hits.append(f"{p.relative_to(ROOT)}:{n}: {m.group(1)!r} in {line.strip()[:100]}")
        self.assertEqual(hits, [], "platform code names the example pack; take it from the pack data instead:\n"
                         + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
