"""Turn unittest failures in a log into GitHub annotations, so CI failures are readable on the PR page.

    python scripts/unittest-annotations.py test.log
"""

import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()


def annotate(title: str, body: str) -> None:
    print(f"::error title={title}::" + body.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))


found = 0
# Each failure: a "FAIL: name" / "ERROR: name" header, a dashed rule, the traceback, up to the next "=====" rule.
for m in re.finditer(r"^(FAIL|ERROR): (.+?)\n-{20,}\n(.*?)(?=^={20,}|^-{20,}\nRan )", text, re.S | re.M):
    kind, name, trace = m.group(1), m.group(2).strip(), m.group(3).strip()
    annotate(f"{kind} {name}", "\n".join(trace.splitlines()[-25:]))  # the assertion and the frames nearest it
    found += 1
for line in text.splitlines():
    if line.startswith("FAIL:") or line.startswith("ERROR:"):
        annotate("failed test", line)
if not found:
    annotate("test run ended", "\n".join(text.splitlines()[-40:]))
