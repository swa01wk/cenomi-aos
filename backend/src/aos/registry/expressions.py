"""Static checks on guard and condition expressions.

Guards and policy conditions are CEL-style expressions evaluated by the kernel (from M2).
At publish time we only need to prove they reference declared names, so a typo or an
undeclared attribute fails validation instead of failing closed at run time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NAMESPACES = ("attr", "workflow", "artifact", "subject", "item")

_STRING = re.compile(r'"[^"]*"|\'[^\']*\'')
_REF = re.compile(r"\b(attr|workflow|artifact|subject|item)\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)")
_CALL = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_.]*)\s*\(\s*(\"[^\"]*\"|'[^']*'|[a-zA-Z_][a-zA-Z0-9_]*)?")
_ALLOWED_TOKENS = re.compile(r"^[\sA-Za-z0-9_.\"'()<>=!&|+\-*/,\[\]]*$")


@dataclass(frozen=True)
class Ref:
    namespace: str
    path: str


@dataclass(frozen=True)
class Call:
    function: str
    argument: str | None


def references(expr: str) -> list[Ref]:
    bare = _STRING.sub('""', expr)
    return [Ref(m.group(1), m.group(2)) for m in _REF.finditer(bare)]


def calls(expr: str) -> list[Call]:
    out = []
    for m in _CALL.finditer(expr):
        arg = m.group(2)
        if arg and arg[0] in "\"'":
            arg = arg[1:-1]
        out.append(Call(m.group(1), arg))
    return out


def syntax_problem(expr: str) -> str | None:
    """A cheap syntax screen: balanced brackets and only expression characters."""
    if not expr.strip():
        return "empty expression"
    if not _ALLOWED_TOKENS.match(expr):
        return "contains characters that cannot appear in a guard expression"
    depth = 0
    for ch in _STRING.sub('""', expr):
        depth += ch in "(["
        depth -= ch in ")]"
        if depth < 0:
            return "unbalanced brackets"
    return "unbalanced brackets" if depth else None
