"""Platform code must not know the example pack.

The kernel, API, gateway, worker, registry and the web app are pack-neutral: domain names, stages, fields and
policies reach them as data from a pack. This test fails if a name from any pack (the pack itself, its workflows,
Seats, Skills, artifact types, connectors, verifiers) or a domain word appears in platform code.

Domain code that a pack points to by `implementation:` (deterministic tools in `aos/tools`, verifiers in
`aos/verifiers`) and the mock connectors (`aos/connectors`) are pack extensions and are not scanned. Fake-model
scripts (`worker/scripts/*.yaml`) are test data and are not scanned either.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from collections import Counter
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
                if p == ROOT / "web/src/api/schema.d.ts":
                    continue
                yield p


# Debt from the demo build (Oct-Nov 2026): lines per file that already name the pack. The test is a ratchet: a file
# may not gain lines, and a file not listed may have none. Lower a count when you clean a file up; regenerate with
#   python -m tests.test_pack_neutral --update   (from backend/, only to record a clean-up, never to admit new hits)
BASELINE = Path(__file__).with_name("pack_neutral_baseline.json")


def _hits() -> list[tuple[str, int, str, str]]:
    terms = _terms()
    pattern = re.compile(r"(?<![a-z0-9_])(" + "|".join(sorted(map(re.escape, terms), key=len, reverse=True))
                         + r")(?![a-z0-9_])", re.I)
    hits = []
    for p in _files():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            if m:
                hits.append((p.relative_to(ROOT).as_posix(), n, m.group(1), line.strip()[:100]))
    return hits


class PackNeutralTest(unittest.TestCase):
    def test_platform_code_does_not_name_the_pack(self) -> None:
        self.assertIn("quick_quote", _terms())  # the scan really reads the pack
        hits = _hits()
        per_file = Counter(f for f, *_ in hits)
        allowed = json.loads(BASELINE.read_text())
        grown = {f: (n, allowed.get(f, 0)) for f, n in per_file.items() if n > allowed.get(f, 0)}
        detail = "\n".join(f"{f}:{n}: {term!r} in {text}" for f, n, term, text in hits if f in grown)
        self.assertEqual(
            grown, {},
            "platform code names the example pack in more lines than before (file: (now, allowed)); take it from"
            " the pack data instead:\n" + detail,
        )


if __name__ == "__main__" and "--update" in sys.argv:
    BASELINE.write_text(json.dumps(dict(sorted(Counter(f for f, *_ in _hits()).items())), indent=1) + "\n")
    print(f"wrote {BASELINE}")

elif __name__ == "__main__":
    unittest.main()
