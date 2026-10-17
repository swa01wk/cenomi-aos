"""The seeded organization: model, consistency checks and seed SQL.

In the POC people come from ``seed/org.yaml`` instead of an identity provider; the shape matches
what an IdP sync will write later.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONSOLE_ROLES = {"platform_admin", "risk", "seat_owner", "process_owner"}


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Team(_S):
    name: str
    owner: str


class Department(_S):
    name: str
    head: str
    teams: dict[str, Team] = Field(min_length=1)


class Person(_S):
    name: str
    team: str = Field(pattern=r"^[a-z0-9_]+/[a-z0-9_]+$")
    roles: list[str] = Field(min_length=1)
    console: bool = False


class Organization(_S):
    id: str
    name: str
    data_residency: str


class OrgModel(_S):
    organization: Organization
    owner_roles: list[str] = []
    departments: dict[str, Department]
    people: dict[str, Person]

    @model_validator(mode="after")
    def _consistent(self) -> "OrgModel":
        teams = {f"{d}/{t}" for d, dept in self.departments.items() for t in dept.teams}
        problems = []
        for pid, p in self.people.items():
            if p.team not in teams:
                problems.append(f"person {pid}: no team {p.team}")
            if p.console and not CONSOLE_ROLES & set(p.roles):
                problems.append(f"person {pid}: console access needs one of {sorted(CONSOLE_ROLES)}")
        for did, d in self.departments.items():
            if d.head not in self.people:
                problems.append(f"department {did}: head {d.head} is not a person")
            for tid, t in d.teams.items():
                if t.owner not in self.people:
                    problems.append(f"team {did}/{tid}: owner {t.owner} is not a person")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def as_validation_org(self) -> dict:
        """The plain dict shape ``aos validate --org`` accepts."""
        return {"people": {k: {} for k in self.people}, "owner_roles": self.owner_roles,
                "departments": {d: {"teams": {t: {} for t in dept.teams}} for d, dept in self.departments.items()}}


def load_org(path: str | Path) -> OrgModel:
    return OrgModel.model_validate(yaml.safe_load(Path(path).read_text()))


def _lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"


def seed_sql(org: OrgModel) -> str:
    """Idempotent seed statements for the org schema (one transaction, deferred FKs)."""
    o = org.organization
    out = ["begin;", "set constraints all deferred;",
           f"insert into org.organizations(id, name, data_residency) values ({_lit(o.id)}, {_lit(o.name)}, "
           f"{_lit(o.data_residency)}) on conflict (id) do nothing;"]
    for did, d in org.departments.items():
        out.append(f"insert into org.departments(org_id, id, name, head_person_id) values ({_lit(o.id)}, {_lit(did)}, "
                   f"{_lit(d.name)}, {_lit(d.head)}) on conflict do nothing;")
        for tid, t in d.teams.items():
            out.append(f"insert into org.teams(org_id, department_id, id, name, owner_person_id) values ({_lit(o.id)}, "
                       f"{_lit(did)}, {_lit(tid)}, {_lit(t.name)}, {_lit(t.owner)}) on conflict do nothing;")
    for pid, p in org.people.items():
        dept, team = p.team.split("/")
        out.append(f"insert into org.people(org_id, id, name, department_id, team_id, console_access) values "
                   f"({_lit(o.id)}, {_lit(pid)}, {_lit(p.name)}, {_lit(dept)}, {_lit(team)}, {_lit(p.console)}) "
                   "on conflict do nothing;")
        for role in p.roles:
            out.append(f"insert into org.role_mappings(org_id, person_id, role) values ({_lit(o.id)}, {_lit(pid)}, "
                       f"{_lit(role)}) on conflict do nothing;")
    out.append("insert into evidence.audit_heads(org_id, last_seq, last_hash) values "
               f"({_lit(o.id)}, 0, '{'0' * 64}') on conflict do nothing;")
    out.append("commit;")
    return "\n".join(out) + "\n"
