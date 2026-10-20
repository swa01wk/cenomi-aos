"""Static checks and runtime evaluation of guard and condition expressions.

Guards and policy conditions are CEL-style expressions evaluated by the kernel (from M2).
At publish time we only need to prove they reference declared names, so a typo or an
undeclared attribute fails validation instead of failing closed at run time.

Runtime evaluation uses three-valued logic: true, false, and unknown (missing refs or
invalid operations). ``evaluate`` returns Python ``True`` only when the result is exactly
true; unknown and any non-boolean top-level form return ``False``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Mapping

NAMESPACES = ("attr", "workflow", "artifact", "subject", "item")

GUARD_FUNCTIONS = frozenset({"same", "reached", "workflow.reached", "all", "any", "size"})

_STRING = re.compile(r'"[^"]*"|\'[^\']*\'')
_REF = re.compile(r"\b(attr|workflow|artifact|subject|item)\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)")
_CALL = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_.]*)\s*\(\s*(\"[^\"]*\"|'[^']*'|[a-zA-Z_][a-zA-Z0-9_]*)?")
_ALLOWED_TOKENS = re.compile(r"^[\sA-Za-z0-9_.\"'()<>=!&|+\-*/,\[\]]*$")

ExpressionScope = Mapping[str, Mapping[str, Any]]


class ExpressionError(ValueError):
    """The string is not a valid expression (syntax)."""


class _Tri(Enum):
    FALSE = auto()
    TRUE = auto()
    UNKNOWN = auto()

    @staticmethod
    def and_(a: _Tri, b: _Tri) -> _Tri:
        if a is _Tri.FALSE or b is _Tri.FALSE:
            return _Tri.FALSE
        if a is _Tri.UNKNOWN or b is _Tri.UNKNOWN:
            return _Tri.UNKNOWN
        return _Tri.TRUE

    @staticmethod
    def or_(a: _Tri, b: _Tri) -> _Tri:
        if a is _Tri.TRUE or b is _Tri.TRUE:
            return _Tri.TRUE
        if a is _Tri.UNKNOWN or b is _Tri.UNKNOWN:
            return _Tri.UNKNOWN
        return _Tri.FALSE

    @staticmethod
    def not_(a: _Tri) -> _Tri:
        if a is _Tri.UNKNOWN:
            return _Tri.UNKNOWN
        return _Tri.FALSE if a is _Tri.TRUE else _Tri.TRUE


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


def evaluate(expr: str, scope: ExpressionScope) -> bool:
    problem = syntax_problem(expr)
    if problem:
        raise ExpressionError(problem)
    try:
        node = _parse(expr)
    except _ParseError as e:
        raise ExpressionError(str(e)) from e
    if not _root_is_boolean(node):
        return False
    return _eval_tri(node, scope) is _Tri.TRUE


# --------------------------------------------------------------------------- parser


class _ParseError(Exception):
    pass


@dataclass
class _Node:
    pass


@dataclass
class _Or(_Node):
    parts: list[_Node]


@dataclass
class _And(_Node):
    parts: list[_Node]


@dataclass
class _Not(_Node):
    inner: _Node


@dataclass
class _Compare(_Node):
    op: str
    left: _Node
    right: _Node


@dataclass
class _Bin(_Node):
    op: str
    left: _Node
    right: _Node


@dataclass
class _Unary(_Node):
    op: str
    inner: _Node


@dataclass
class _Ref(_Node):
    namespace: str
    path: str


@dataclass
class _BareName(_Node):
    """Unqualified name, e.g. the attribute in ``same(brief_version)``."""

    name: str


@dataclass
class _Literal(_Node):
    value: bool | int | Decimal | str


@dataclass
class _Call(_Node):
    name: str
    args: list[_Node]


def _root_is_boolean(node: _Node) -> bool:
    if isinstance(node, (_Or, _And, _Not, _Compare, _Call)):
        if isinstance(node, _Call):
            base = node.name.split(".")[-1]
            return base in {"same", "reached", "all", "any"}
        return True
    return False


def _parse(expr: str) -> _Node:
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    node = parser.or_expr()
    if parser.peek() is not None:
        raise _ParseError("unexpected trailing input")
    return node


class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, Any] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def pop(self) -> tuple[str, Any]:
        tok = self.peek()
        if tok is None:
            raise _ParseError("unexpected end of expression")
        self.pos += 1
        return tok

    def expect(self, kind: str) -> Any:
        tok = self.pop()
        if tok[0] != kind:
            raise _ParseError(f"expected {kind}, got {tok[0]}")
        return tok[1]

    def or_expr(self) -> _Node:
        parts = [self.and_expr()]
        while self.peek() and self.peek()[0] == "OP" and self.peek()[1] == "||":
            self.pop()
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else _Or(parts)

    def and_expr(self) -> _Node:
        parts = [self.not_expr()]
        while self.peek() and self.peek()[0] == "OP" and self.peek()[1] == "&&":
            self.pop()
            parts.append(self.not_expr())
        return parts[0] if len(parts) == 1 else _And(parts)

    def not_expr(self) -> _Node:
        if self.peek() and self.peek()[0] == "OP" and self.peek()[1] == "!":
            self.pop()
            return _Not(self.not_expr())
        return self.cmp_expr()

    def cmp_expr(self) -> _Node:
        left = self.add_expr()
        if self.peek() and self.peek()[0] == "OP" and self.peek()[1] in ("==", "!=", ">=", "<=", ">", "<"):
            op = self.pop()[1]
            right = self.add_expr()
            return _Compare(op, left, right)
        return left

    def add_expr(self) -> _Node:
        left = self.mul_expr()
        while self.peek() and self.peek()[0] == "OP" and self.peek()[1] in ("+", "-"):
            op = self.pop()[1]
            left = _Bin(op, left, self.mul_expr())
        return left

    def mul_expr(self) -> _Node:
        left = self.unary_expr()
        while self.peek() and self.peek()[0] == "OP" and self.peek()[1] in ("*", "/"):
            op = self.pop()[1]
            left = _Bin(op, left, self.unary_expr())
        return left

    def unary_expr(self) -> _Node:
        if self.peek() and self.peek()[0] == "OP" and self.peek()[1] == "-":
            self.pop()
            return _Unary("-", self.unary_expr())
        return self.primary()

    def primary(self) -> _Node:
        tok = self.peek()
        if tok is None:
            raise _ParseError("unexpected end of expression")
        if tok[0] == "LPAREN":
            self.pop()
            inner = self.or_expr()
            self.expect("RPAREN")
            return inner
        if tok[0] == "LITERAL":
            self.pop()
            return _Literal(tok[1])
        if tok[0] == "REF":
            self.pop()
            return _Ref(tok[1][0], tok[1][1])
        if tok[0] == "IDENT":
            self.pop()
            name = tok[1]
            if self.peek() and self.peek()[0] == "LPAREN":
                self.pop()
                args: list[_Node] = []
                if self.peek() and self.peek()[0] != "RPAREN":
                    args.append(self.or_expr())
                    while self.peek() and self.peek()[0] == "COMMA":
                        self.pop()
                        args.append(self.or_expr())
                self.expect("RPAREN")
                return _Call(name, args)
            return _BareName(name)
        raise _ParseError(f"unexpected token {tok[0]}")


def _tokenize(expr: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    i = 0
    n = len(expr)

    def at(k: str) -> bool:
        return expr.startswith(k, i)

    while i < n:
        if expr[i].isspace():
            i += 1
            continue
        if at("&&"):
            out.append(("OP", "&&"))
            i += 2
            continue
        if at("||"):
            out.append(("OP", "||"))
            i += 2
            continue
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if at(op):
                out.append(("OP", op))
                i += len(op)
                break
        else:
            if expr[i] in "+-*/!":
                out.append(("OP", expr[i]))
                i += 1
                continue
            if expr[i] == "(":
                out.append(("LPAREN", "("))
                i += 1
                continue
            if expr[i] == ")":
                out.append(("RPAREN", ")"))
                i += 1
                continue
            if expr[i] == ",":
                out.append(("COMMA", ","))
                i += 1
                continue
            if expr[i] in "\"'":
                q = expr[i]
                j = i + 1
                while j < n and expr[j] != q:
                    j += 1
                if j >= n:
                    raise _ParseError("unterminated string")
                out.append(("LITERAL", expr[i + 1 : j]))
                i = j + 1
                continue
            if expr[i].isdigit() or (expr[i] == "." and i + 1 < n and expr[i + 1].isdigit()):
                j = i
                while j < n and (expr[j].isdigit() or expr[j] == "."):
                    j += 1
                num = expr[i:j]
                if num.count(".") > 1 or num.endswith("."):
                    raise _ParseError(f"invalid number {num!r}")
                out.append(("LITERAL", Decimal(num) if "." in num else int(num)))
                i = j
                continue
            if expr[i].isalpha() or expr[i] == "_":
                j = i
                while j < n and (expr[j].isalnum() or expr[j] in "._"):
                    j += 1
                word = expr[i:j]
                i = j
                if word in ("true", "false"):
                    out.append(("LITERAL", word == "true"))
                    continue
                parts = word.split(".", 1)
                j = i
                while j < n and expr[j].isspace():
                    j += 1
                if parts[0] in NAMESPACES and len(parts) == 2 and (j >= n or expr[j] != "("):
                    out.append(("REF", (parts[0], parts[1])))
                    continue
                out.append(("IDENT", word))
                continue
            raise _ParseError(f"invalid character {expr[i]!r}")
    return out


# --------------------------------------------------------------------------- evaluation


@dataclass
class _Val:
    unknown: bool = False
    kind: str | None = None  # bool, num, str, list
    data: Any = None

    @staticmethod
    def unk() -> _Val:
        return _Val(unknown=True)

    @staticmethod
    def of_bool(v: bool) -> _Val:
        return _Val(kind="bool", data=v)

    @staticmethod
    def of_num(v: int | Decimal) -> _Val:
        return _Val(kind="num", data=v)

    @staticmethod
    def of_str(v: str) -> _Val:
        return _Val(kind="str", data=v)

    @staticmethod
    def of_list(v: list[Any]) -> _Val:
        return _Val(kind="list", data=v)


def _lookup(scope: ExpressionScope, namespace: str, path: str) -> _Val:
    if namespace not in scope:
        return _Val.unk()
    root = scope[namespace]
    if not isinstance(root, Mapping):
        return _Val.unk()
    cur: Any = root
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return _Val.unk()
        cur = cur[part]
    if cur is None:
        return _Val.unk()
    if isinstance(cur, bool):
        return _Val.of_bool(cur)
    if isinstance(cur, (int, Decimal)):
        return _Val.of_num(cur)
    if isinstance(cur, float):
        return _Val.of_num(Decimal(str(cur)))
    if isinstance(cur, str):
        return _Val.of_str(cur)
    if isinstance(cur, (list, tuple)):
        return _Val.of_list(list(cur))
    return _Val.unk()


def _as_num(v: _Val) -> _Val:
    if v.unknown:
        return _Val.unk()
    if v.kind == "num":
        return v
    return _Val.unk()


def _eval_val(node: _Node, scope: ExpressionScope) -> _Val:
    if isinstance(node, _BareName):
        return _Val.unk()
    if isinstance(node, _Literal):
        if isinstance(node.value, bool):
            return _Val.of_bool(node.value)
        if isinstance(node.value, str):
            return _Val.of_str(node.value)
        return _Val.of_num(node.value)
    if isinstance(node, _Ref):
        return _lookup(scope, node.namespace, node.path)
    if isinstance(node, _Unary):
        v = _eval_val(node.inner, scope)
        n = _as_num(v)
        if n.unknown:
            return _Val.unk()
        return _Val.of_num(-n.data)
    if isinstance(node, _Bin):
        left, right = _eval_val(node.left, scope), _eval_val(node.right, scope)
        ln, rn = _as_num(left), _as_num(right)
        if ln.unknown or rn.unknown:
            return _Val.unk()
        if node.op == "+":
            return _Val.of_num(ln.data + rn.data)
        if node.op == "-":
            return _Val.of_num(ln.data - rn.data)
        if node.op == "*":
            return _Val.of_num(ln.data * rn.data)
        if node.op == "/":
            if rn.data == 0:
                return _Val.unk()
            return _Val.of_num(ln.data / rn.data)
        return _Val.unk()
    if isinstance(node, _Call):
        return _eval_call(node, scope)
    return _Val.unk()


def _eval_tri(node: _Node, scope: ExpressionScope) -> _Tri:
    if isinstance(node, _Literal) and isinstance(node.value, bool):
        return _Tri.TRUE if node.value else _Tri.FALSE
    if isinstance(node, _Or):
        acc = _Tri.FALSE
        for part in node.parts:
            acc = _Tri.or_(acc, _eval_tri(part, scope))
        return acc
    if isinstance(node, _And):
        acc = _Tri.TRUE
        for part in node.parts:
            acc = _Tri.and_(acc, _eval_tri(part, scope))
        return acc
    if isinstance(node, _Not):
        return _Tri.not_(_eval_tri(node.inner, scope))
    if isinstance(node, _Compare):
        return _eval_compare(node, scope)
    if isinstance(node, _Call):
        v = _eval_call(node, scope)
        if v.unknown:
            return _Tri.UNKNOWN
        if v.kind == "bool":
            return _Tri.TRUE if v.data else _Tri.FALSE
        return _Tri.UNKNOWN
    return _Tri.UNKNOWN


def _eval_compare(node: _Compare, scope: ExpressionScope) -> _Tri:
    left, right = _eval_val(node.left, scope), _eval_val(node.right, scope)
    if left.unknown or right.unknown:
        return _Tri.UNKNOWN
    op = node.op
    if op in ("==", "!="):
        eq = _values_equal(left, right)
        if eq is None:
            return _Tri.UNKNOWN
        return _Tri.TRUE if (eq and op == "==") or (not eq and op == "!=") else _Tri.FALSE
    ln, rn = _as_num(left), _as_num(right)
    if ln.unknown or rn.unknown:
        return _Tri.UNKNOWN
    try:
        cmp = _compare_nums(ln.data, rn.data, op)
    except _CompareError:
        return _Tri.UNKNOWN
    return _Tri.TRUE if cmp else _Tri.FALSE


class _CompareError(Exception):
    pass


def _values_equal(a: _Val, b: _Val) -> bool | None:
    if a.kind == b.kind:
        if a.kind in ("bool", "str", "num", "list"):
            return a.data == b.data
    an, bn = _as_num(a), _as_num(b)
    if not an.unknown and not bn.unknown:
        return an.data == bn.data
    if a.kind == "str" or b.kind == "str":
        if a.kind != b.kind:
            return None
    return None


def _compare_nums(l: int | Decimal, r: int | Decimal, op: str) -> bool:
    if op == ">":
        return l > r
    if op == "<":
        return l < r
    if op == ">=":
        return l >= r
    if op == "<=":
        return l <= r
    raise _CompareError(op)


def _eval_call(node: _Call, scope: ExpressionScope) -> _Val:
    name = node.name
    base = name.split(".")[-1]

    if base == "same":
        if len(node.args) != 1:
            return _Val.unk()
        arg = node.args[0]
        if isinstance(arg, _BareName):
            attr_name = arg.name
        elif isinstance(arg, _Literal) and isinstance(arg.value, str):
            attr_name = arg.value
        elif isinstance(arg, _Ref) and arg.namespace == "attr":
            attr_name = arg.path.split(".")[0]
        else:
            return _Val.unk()
        # Provisional: M2-BE-02 defines what workflow.started_with holds for the join (the branch's
        # input version); this comparison may change when that lands.
        wf = scope.get("workflow")
        if not isinstance(wf, Mapping):
            return _Val.unk()
        sw = wf.get("started_with")
        if not isinstance(sw, Mapping) or attr_name not in sw:
            return _Val.unk()
        lv = _coerce_value(sw[attr_name])
        right_val = _lookup(scope, "attr", attr_name)
        if lv.unknown or right_val.unknown:
            return _Val.unk()
        eq = _values_equal(lv, right_val)
        if eq is None:
            return _Val.unk()
        return _Val.of_bool(eq)

    if base == "reached":
        if len(node.args) != 1:
            return _Val.unk()
        st = _eval_val(node.args[0], scope)
        if st.kind != "str":
            return _Val.unk()
        reached = _lookup(scope, "workflow", "reached")
        if reached.unknown:
            return _Val.unk()
        if reached.kind == "list":
            return _Val.of_bool(st.data in reached.data)
        return _Val.unk()

    if base in ("all", "any"):
        # Same three-valued rules as && and ||: a false (all) or true (any) argument decides, wherever it is.
        if not node.args:
            return _Val.unk()
        combine = _Tri.and_ if base == "all" else _Tri.or_
        acc = _Tri.TRUE if base == "all" else _Tri.FALSE
        for arg in node.args:
            acc = combine(acc, _eval_tri(arg, scope))
        if acc is _Tri.UNKNOWN:
            return _Val.unk()
        return _Val.of_bool(acc is _Tri.TRUE)

    if base == "size":
        if len(node.args) != 1:
            return _Val.unk()
        v = _eval_val(node.args[0], scope)
        if v.unknown:
            return _Val.unk()
        if v.kind in ("list", "str"):
            return _Val.of_num(len(v.data))
        return _Val.unk()

    return _Val.unk()


def _coerce_value(raw: Any) -> _Val:
    if raw is None:
        return _Val.unk()
    if isinstance(raw, bool):
        return _Val.of_bool(raw)
    if isinstance(raw, (int, Decimal)):
        return _Val.of_num(raw)
    if isinstance(raw, float):
        return _Val.of_num(Decimal(str(raw)))
    if isinstance(raw, str):
        return _Val.of_str(raw)
    return _Val.unk()
