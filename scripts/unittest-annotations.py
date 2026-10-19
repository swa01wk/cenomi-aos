"""Turn unittest failures in a log into GitHub annotations, so CI failures are readable on the PR page.

    python scripts/unittest-annotations.py test.log
"""

import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
# Each failure: a "FAIL: name" / "ERROR: name" header, a dashed rule, the traceback, up to the next "=====" rule.
for m in re.finditer(r"^(FAIL|ERROR): (.+?)\n-{20,}\n(.*?)(?=^={20,}|^-{20,}\nRan )", text, re.S | re.M):
    kind, name, trace = m.group(1), m.group(2).strip(), m.group(3).strip()
    tail = "\n".join(trace.splitlines()[-25:])  # the assertion and the frames nearest it
    body = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={kind} {name}::{body}")
