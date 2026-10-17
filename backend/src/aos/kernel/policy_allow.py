"""M1 tool authority check: authority-profile grants only (full engine in M3)."""

from __future__ import annotations

from typing import Any, Literal

Effect = Literal["ALLOW", "DENY", "NEVER", "REQUIRE_APPROVAL"]

_STRICTNESS = {"NEVER": 4, "DENY": 3, "REQUIRE_APPROVAL": 2, "ALLOW": 1}


def _matching_grants(grants: list[dict[str, Any]], resource: str, action: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for grant in grants:
        if grant.get("resource") != resource:
            continue
        actions = grant.get("actions") or []
        if action not in actions:
            continue
        out.append(grant)
    return out


def authority_rule_id(profile_name: str, profile_version: int, resource: str, action: str, suffix: str) -> str:
    return f"authority.{profile_name}@{profile_version}.{resource}.{action}.{suffix}"


def evaluate_tool_authority(
    grants: list[dict[str, Any]],
    *,
    resource: str,
    action: str,
    scope_resources: list[str],
    profile_name: str,
    profile_version: int,
) -> tuple[bool, str | None, str | None]:
    """Return (allowed, refusal_code, rule). Deny overrides ALLOW in M1."""
    if resource not in scope_resources:
        return (
            False,
            "not_permitted",
            authority_rule_id(profile_name, profile_version, resource, action, "scope"),
        )
    matched = _matching_grants(grants, resource, action)
    if not matched:
        return (
            False,
            "not_permitted",
            authority_rule_id(profile_name, profile_version, resource, action, "default_deny"),
        )
    worst: tuple[int, str, str] | None = None
    has_allow = False
    for grant in matched:
        effect = str(grant.get("effect") or "DENY")
        if effect == "ALLOW":
            has_allow = True
            continue
        rank = _STRICTNESS.get(effect, 3)  # type: ignore[arg-type]
        code = "policy_never" if effect == "NEVER" else "policy_denied"
        rule = authority_rule_id(profile_name, profile_version, resource, action, effect.lower())
        if worst is None or rank > worst[0]:
            worst = (rank, code, rule)
    if worst is not None:
        return False, worst[1], worst[2]
    if has_allow:
        return True, None, authority_rule_id(profile_name, profile_version, resource, action, "allow")
    return (
        False,
        "not_permitted",
        authority_rule_id(profile_name, profile_version, resource, action, "default_deny"),
    )
