"""Cross-reference validation for a loaded pack: everything ``aos validate`` checks beyond schemas.

Each check emits an Issue with a stable code, so tests and the Console can key on it.
"""

from __future__ import annotations

from collections import deque
from pathlib import PurePosixPath

from . import expressions as ex
from .kinds import (BUILTIN_RESOLVERS, NATIVE_TOOLS, ArtifactType, EvalSuite, Policy, Resource, Role, Seat,
                    Skill, TaskTemplate, ToolProvider, Verifier, WorkflowDefinition)
from .loader import LoadedPack, load_pack
from .report import Issue, ValidationReport

WORKFLOW_FIELDS = {"state", "status", "version", "definition", "reached"}
SUBJECT_FIELDS = {"role", "participant_roles", "id"}
EFFECT_KEYS = {"start_timer", "cancel_timers", "lock", "handover", "outcome_record", "bind"}
GUARD_FUNCTIONS = set(ex.GUARD_FUNCTIONS)


class _Checker:
    def __init__(self, pack: LoadedPack, org: dict | None):
        self.p = pack
        self.org = org
        self.issues: list[Issue] = []
        self.roles: dict[str, Role] = pack.get("Role")  # type: ignore[assignment]
        self.resources: dict[str, Resource] = pack.get("Resource")  # type: ignore[assignment]
        self.artifacts: dict[str, ArtifactType] = pack.get("ArtifactType")  # type: ignore[assignment]
        self.seats: dict[str, Seat] = pack.get("Seat")  # type: ignore[assignment]
        self.skills: dict[str, Skill] = pack.get("Skill")  # type: ignore[assignment]
        self.verifiers: dict[str, Verifier] = pack.get("Verifier")  # type: ignore[assignment]
        self.providers: dict[str, ToolProvider] = pack.get("ToolProvider")  # type: ignore[assignment]
        self.policies: dict[str, Policy] = pack.get("Policy")  # type: ignore[assignment]
        self.workflows: dict[str, WorkflowDefinition] = pack.get("WorkflowDefinition")  # type: ignore[assignment]
        self.evals: dict[str, EvalSuite] = pack.get("EvalSuite")  # type: ignore[assignment]
        self.tools: dict[str, tuple[str, object]] = {}  # tool -> (provider, ToolSpec)
        self.inbound_events: set[str] = set()
        self.artifact_fields = {f for a in self.artifacts.values() for f in a.spec.fields}

    # ------------------------------------------------------------ helpers
    def err(self, code: str, kind: str, name: str, path: str, msg: str, severity: str = "error") -> None:
        file = self.p.files.get((kind, name), name)
        self.issues.append(Issue(code, file, path, msg, severity))

    def warn(self, code: str, kind: str, name: str, path: str, msg: str) -> None:
        self.err(code, kind, name, path, msg, "warning")

    def ref(self, kind: str, name: str, path: str, target_kind: str, target: str, pool) -> bool:
        if target not in pool:
            self.err("E_REF", kind, name, path, f"{target_kind} {target!r} is not defined in the pack")
            return False
        return True

    # ------------------------------------------------------------ checks
    def run(self) -> list[Issue]:
        self.check_providers()
        self.check_artifacts()
        self.check_verifiers()
        self.check_skills()
        self.check_policies()
        self.check_seats()
        self.check_workflows()
        self.check_evals()
        self.check_effect_governance()
        self.check_manifest()
        self.check_owners()
        return self.issues

    def check_providers(self) -> None:
        for pname, prov in self.providers.items():
            if prov.spec.inbound:
                self.inbound_events.add(prov.spec.inbound.event)
            for tname, tool in prov.spec.tools.items():
                path = f"spec.tools.{tname}"
                if tname in self.tools:
                    self.err("E_DUPLICATE", "ToolProvider", pname, path,
                             f"tool {tname!r} is also provided by {self.tools[tname][0]!r}")
                    continue
                if tname in NATIVE_TOOLS:
                    self.err("E_DUPLICATE", "ToolProvider", pname, path, f"{tname!r} is a kernel-native tool")
                self.tools[tname] = (pname, tool)
                if self.ref("ToolProvider", pname, f"{path}.resource", "Resource", tool.resource, self.resources):
                    if tool.action not in self.resources[tool.resource].spec.actions:
                        self.err("E_ACTION", "ToolProvider", pname, f"{path}.action",
                                 f"resource {tool.resource!r} has no action {tool.action!r}")
                if tool.reconcile_with:
                    other = prov.spec.tools.get(tool.reconcile_with)
                    if other is None or other.tool_class != "read":
                        self.err("E_RECONCILE", "ToolProvider", pname, f"{path}.reconcile_with",
                                 f"{tool.reconcile_with!r} must be a read tool of the same provider")
                if prov.spec.transport == "builtin" and not tool.implementation:
                    self.err("E_IMPLEMENTATION", "ToolProvider", pname, path, "a builtin tool needs an implementation")
                if prov.spec.transport == "mcp" and tool.tool_class == "read" and not tool.input_schema:
                    self.err("E_INPUT_SCHEMA", "ToolProvider", pname, path, "an mcp read tool needs input_schema")

    def check_artifacts(self) -> None:
        participants = {r for w in self.workflows.values() for r in w.spec.participants}
        for name, at in self.artifacts.items():
            fields = at.spec.fields
            for col in at.spec.view.columns or []:
                if col not in fields:
                    self.err("E_VIEW_COLUMN", "ArtifactType", name, "spec.view.columns", f"no field {col!r}")
            if at.spec.view.type in ("sheet", "tracker", "comparison") and not at.spec.view.columns:
                self.err("E_VIEW_COLUMN", "ArtifactType", name, "spec.view", "a table view needs columns")
            for role, vis in at.spec.visibility.items():
                if participants and role not in participants:
                    self.err("E_REF", "ArtifactType", name, f"spec.visibility.{role}",
                             f"{role!r} is not a participant role in any workflow")
                if isinstance(vis, list):
                    for f in vis:
                        if f not in fields:
                            self.err("E_VISIBILITY", "ArtifactType", name, f"spec.visibility.{role}",
                                     f"no field {f!r}")
            if at.spec.classification == "shareable":
                for fname, f in fields.items():
                    if f.classification in ("internal", "restricted"):
                        self.err("E_CLASSIFICATION", "ArtifactType", name, f"spec.fields.{fname}",
                                 "a shareable artifact type cannot hold internal or restricted fields")
            if at.spec.row_key is not None and at.spec.row_key not in fields:
                self.err(
                    "E_REF",
                    "ArtifactType",
                    name,
                    "spec.row_key",
                    f"no field {at.spec.row_key!r}",
                )
        self._check_decision_row_keys()

    def _check_decision_row_keys(self) -> None:
        for wname, wf in self.workflows.items():
            for dname, dec in wf.spec.decisions.items():
                if not dec.selection:
                    continue
                st = wf.spec.states.get(dec.state)
                if st is None or not st.view:
                    continue
                at = self.artifacts.get(st.view)
                if at is None or not at.spec.row_based:
                    continue
                if not at.spec.row_key:
                    self.err(
                        "E_DECISION",
                        "WorkflowDefinition",
                        wname,
                        f"spec.decisions.{dname}",
                        f"selection decision needs row_key on row-based ArtifactType {st.view!r}",
                    )

    def check_verifiers(self) -> None:
        for name, v in self.verifiers.items():
            for i, at in enumerate(v.spec.applies_to):
                self.ref("Verifier", name, f"spec.applies_to[{i}]", "ArtifactType", at, self.artifacts)

    def check_skills(self) -> None:
        for name, sk in self.skills.items():
            folder = PurePosixPath(self.p.files[("Skill", name)]).parent
            instr = (folder / sk.spec.instructions).as_posix()
            if instr not in self.p.support_files:
                self.err("E_FILE", "Skill", name, "spec.instructions", f"instructions file {instr!r} not found")
            for i, r in enumerate(sk.spec.reads):
                if r not in BUILTIN_RESOLVERS and r not in self.artifacts:
                    self.err("E_REF", "Skill", name, f"spec.reads[{i}]",
                             f"{r!r} is neither a kernel resolver {BUILTIN_RESOLVERS} nor an artifact type")
            for i, at in enumerate(sk.spec.produces):
                self.ref("Skill", name, f"spec.produces[{i}]", "ArtifactType", at, self.artifacts)
            for i, t in enumerate(sk.spec.may_request):
                if t not in NATIVE_TOOLS and t not in self.tools:
                    self.err("E_REF", "Skill", name, f"spec.may_request[{i}]", f"tool {t!r} is not provided")
            for i, v in enumerate(sk.spec.verifiers):
                if self.ref("Skill", name, f"spec.verifiers[{i}]", "Verifier", v, self.verifiers):
                    if not set(self.verifiers[v].spec.applies_to) & set(sk.spec.produces):
                        self.warn("W_VERIFIER_SCOPE", "Skill", name, f"spec.verifiers[{i}]",
                                  f"verifier {v!r} checks none of the artifacts this skill produces")

    def _check_expr(self, kind: str, name: str, path: str, expr: str, attrs: set[str],
                    states: set[str] | None) -> None:
        problem = ex.syntax_problem(expr)
        if problem:
            self.err("E_EXPRESSION", kind, name, path, f"{problem}: {expr!r}")
            return
        for r in ex.references(expr):
            head = r.path.split(".")[0]
            if r.namespace == "attr" and head not in attrs:
                self.err("E_ATTRIBUTE", kind, name, path, f"undeclared attribute attr.{head}")
            elif r.namespace == "workflow" and head not in WORKFLOW_FIELDS:
                self.err("E_ATTRIBUTE", kind, name, path, f"workflow has no attribute {head!r}")
            elif r.namespace == "subject" and head not in SUBJECT_FIELDS:
                self.err("E_ATTRIBUTE", kind, name, path, f"subject has no attribute {head!r}")
            elif r.namespace == "artifact":
                if head == "verification":
                    parts = r.path.split(".")
                    if len(parts) < 2 or parts[1] not in self.verifiers:
                        self.err("E_ATTRIBUTE", kind, name, path, f"artifact.{r.path}: no such verifier")
                elif head not in self.artifact_fields and head not in ("version", "digest", "classification"):
                    self.err("E_ATTRIBUTE", kind, name, path, f"no artifact type declares field {head!r}")
        for c in ex.calls(expr):
            fn = c.function.split(".")[-1]
            if fn not in {f.split(".")[-1] for f in GUARD_FUNCTIONS}:
                self.err("E_EXPRESSION", kind, name, path, f"unknown function {c.function!r}")
            elif fn == "same" and c.argument not in attrs:
                self.err("E_ATTRIBUTE", kind, name, path, f"same() needs a declared attribute, got {c.argument!r}")
            elif fn == "reached" and states is not None and c.argument not in states:
                self.err("E_REF", kind, name, path, f"reached() names unknown state {c.argument!r}")

    def check_policies(self) -> None:
        for name, pol in self.policies.items():
            for i, g in enumerate(pol.spec.grants):
                if self.ref("Policy", name, f"spec.grants[{i}].resource", "Resource", g.resource, self.resources):
                    for a in g.actions:
                        if a not in self.resources[g.resource].spec.actions:
                            self.err("E_ACTION", "Policy", name, f"spec.grants[{i}].actions",
                                     f"resource {g.resource!r} has no action {a!r}")
            wf = None
            if pol.spec.workflow and self.ref("Policy", name, "spec.workflow", "WorkflowDefinition",
                                              pol.spec.workflow, self.workflows):
                wf = self.workflows[pol.spec.workflow]
            attrs = set(wf.spec.attributes) if wf else set()
            states = set(wf.spec.states) if wf else None
            participants = set(wf.spec.participants) if wf else set()
            for i, rule in enumerate(pol.spec.rules):
                base = f"spec.rules[{i}]"
                res, act = rule.action.split(".")
                if self.ref("Policy", name, f"{base}.action", "Resource", res, self.resources):
                    if act not in self.resources[res].spec.actions:
                        self.err("E_ACTION", "Policy", name, f"{base}.action", f"resource {res!r} has no action {act!r}")
                for j, cond in enumerate(rule.conditions):
                    self._check_expr("Policy", name, f"{base}.conditions[{j}]", cond, attrs, states)
                for j, subj in enumerate(rule.subjects):
                    role = subj.removeprefix("participant:")
                    if wf and role not in participants:
                        self.err("E_REF", "Policy", name, f"{base}.subjects[{j}]",
                                 f"{role!r} is not a participant of {wf.metadata.name}")
                if rule.approval:
                    for j, step in enumerate(rule.approval.chain):
                        role = step.approver.removeprefix("participant:")
                        if wf and role not in participants:
                            self.err("E_REF", "Policy", name, f"{base}.approval.chain[{j}].approver",
                                     f"{role!r} is not a participant of {wf.metadata.name}")
                        if step.when:
                            self._check_expr("Policy", name, f"{base}.approval.chain[{j}].when", step.when,
                                             attrs, states)

    def check_seats(self) -> None:
        for name, seat in self.seats.items():
            s = seat.spec
            role = self.roles.get(s.role)
            self.ref("Seat", name, "spec.role", "Role", s.role, self.roles)
            if self.ref("Seat", name, "spec.assist_skill", "Skill", s.assist_skill, self.skills):
                if s.assist_skill not in s.skills:
                    self.err(
                        "E_ASSIST_SKILL",
                        "Seat",
                        name,
                        "spec.assist_skill",
                        f"assist_skill {s.assist_skill!r} must be listed in spec.skills",
                    )
            for i, sk in enumerate(s.skills):
                if self.ref("Seat", name, f"spec.skills[{i}]", "Skill", sk, self.skills) and role:
                    extra = set(self.skills[sk].spec.work_types) - set(role.spec.work_types)
                    if extra:
                        self.err("E_ROLE_WORKTYPE", "Seat", name, f"spec.skills[{i}]",
                                 f"skill {sk!r} needs Work Types {sorted(extra)} that role {s.role!r} does not permit")
            for i, r in enumerate(s.resources):
                self.ref("Seat", name, f"spec.resources[{i}]", "Resource", r, self.resources)
            prof_name, _, prof_ver = s.authority_profile.partition("@")
            prof = self.policies.get(prof_name)
            if prof is None:
                self.err("E_REF", "Seat", name, "spec.authority_profile", f"no Policy {prof_name!r}")
            elif prof.spec.type != "authority_profile":
                self.err("E_REF", "Seat", name, "spec.authority_profile", f"{prof_name!r} is not an authority profile")
            elif prof.metadata.version != int(prof_ver):
                self.err("E_VERSION", "Seat", name, "spec.authority_profile",
                         f"pinned v{prof_ver} but the pack has v{prof.metadata.version}")
            else:
                for i, g in enumerate(prof.spec.grants):
                    if g.resource not in s.resources:
                        self.err("E_GRANT_SCOPE", "Seat", name, "spec.authority_profile",
                                 f"profile grants on {g.resource!r}, which is not assigned to this Seat")
            for i, e in enumerate(s.evals):
                if self.ref("Seat", name, f"spec.evals[{i}]", "EvalSuite", e, self.evals):
                    if name not in self.evals[e].spec.targets:
                        self.err("E_REF", "Seat", name, f"spec.evals[{i}]", f"eval suite {e!r} does not target this Seat")
            if s.delegation:
                for t in s.delegation.targets:
                    self.ref("Seat", name, "spec.delegation.targets", "Role", t, self.roles)

    def _check_template(
        self,
        wname: str,
        path: str,
        t: TaskTemplate,
        role: Role | None,
        seats_for_role: list[Seat],
        participants: set[str],
    ) -> None:
        if t.on_behalf_of is not None and t.on_behalf_of not in participants:
            self.err(
                "E_REF",
                "WorkflowDefinition",
                wname,
                f"{path}.on_behalf_of",
                f"{t.on_behalf_of!r} is not a participant",
            )
        if self.ref("WorkflowDefinition", wname, f"{path}.skill", "Skill", t.skill, self.skills):
            if t.work_type not in self.skills[t.skill].spec.work_types:
                self.err("E_SKILL_WORKTYPE", "WorkflowDefinition", wname, path,
                         f"skill {t.skill!r} is not written for Work Type {t.work_type!r}")
            if seats_for_role and not any(t.skill in s.spec.skills for s in seats_for_role):
                self.err("E_SEAT_SKILL", "WorkflowDefinition", wname, path,
                         f"no Seat with the workflow's role has skill {t.skill!r}")
        if role and t.work_type not in role.spec.work_types:
            self.err("E_ROLE_WORKTYPE", "WorkflowDefinition", wname, path,
                     f"template {t.template!r} sends Work Type {t.work_type!r} to role {role.metadata.name!r}, "
                     "which does not permit it")
        if t.verifier:
            self.ref("WorkflowDefinition", wname, f"{path}.verifier", "Verifier", t.verifier, self.verifiers)

    def _org_role_names(self) -> set[str]:
        if not self.org:
            return set()
        names: set[str] = set(self.org.get("owner_roles", []))
        for person in self.org.get("people", {}).values():
            names.update(person.get("roles", []))
        return names

    def check_workflows(self) -> None:
        for wname, wf in self.workflows.items():
            w = wf.spec
            K = "WorkflowDefinition"
            states = set(w.states)
            attrs = set(w.attributes)
            participants = set(w.participants)
            role = self.roles.get(w.seat_role)
            self.ref(K, wname, "spec.seat_role", "Role", w.seat_role, self.roles)
            seats_for_role = [s for s in self.seats.values() if s.spec.role == w.seat_role]
            if role and not seats_for_role:
                self.err("E_NO_SEAT", K, wname, "spec.seat_role", f"no Seat has role {w.seat_role!r}")
            if w.initial not in states:
                self.err("E_REF", K, wname, "spec.initial", f"no state {w.initial!r}")
            org_roles = self._org_role_names()
            for i, r in enumerate(w.start_roles):
                if r not in participants:
                    self.err("E_REF", K, wname, f"spec.start_roles[{i}]", f"{r!r} is not a participant")
                p = w.participants[r]
                if not p.org_roles:
                    self.err(
                        "E_PARTICIPANT",
                        K,
                        wname,
                        f"spec.participants.{r}.org_roles",
                        "a start role participant needs org_roles",
                    )
                for j, orole in enumerate(p.org_roles):
                    if orole not in org_roles:
                        self.err(
                            "E_REF",
                            K,
                            wname,
                            f"spec.participants.{r}.org_roles[{j}]",
                            f"{orole!r} is not an org role",
                        )
            for pname, p in w.participants.items():
                if p.bind == "by_claim" and not p.queue:
                    self.err("E_PARTICIPANT", K, wname, f"spec.participants.{pname}", "by_claim needs a queue")
                if p.bind == "by_rule" and not p.rule:
                    self.err("E_PARTICIPANT", K, wname, f"spec.participants.{pname}", "by_rule needs a rule")

            templates_by_state: dict[str, set[str]] = {}
            all_templates: set[str] = set()
            for sname, st in w.states.items():
                base = f"spec.states.{sname}"
                if st.view:
                    self.ref(K, wname, f"{base}.view", "ArtifactType", st.view, self.artifacts)
                if st.assist:
                    if not seats_for_role:
                        self.err(
                            "E_STATE_ASSIST",
                            K,
                            wname,
                            f"{base}.assist",
                            "no Seat has the workflow's role to validate assist",
                        )
                    elif not any(st.assist in seat.spec.skills for seat in seats_for_role):
                        self.err(
                            "E_STATE_ASSIST",
                            K,
                            wname,
                            f"{base}.assist",
                            f"assist skill {st.assist!r} is not on any Seat with role {w.seat_role!r}",
                        )
                    else:
                        self.ref(K, wname, f"{base}.assist", "Skill", st.assist, self.skills)
                if st.final and (st.tasks or st.on_event):
                    self.err("E_FINAL", K, wname, base, "a final state cannot create Tasks")
                names = set()
                for i, t in enumerate(st.tasks):
                    self._check_template(wname, f"{base}.tasks[{i}]", t, role, seats_for_role, participants)
                    names.add(t.template)
                for ev, t in st.on_event.items():
                    if ev not in self.inbound_events:
                        self.err("E_EVENT", K, wname, f"{base}.on_event",
                                 f"{ev!r} is not an inbound event of any connector {sorted(self.inbound_events)}")
                    self._check_template(wname, f"{base}.on_event.{ev}", t, role, seats_for_role, participants)
                    names.add(t.template)
                dup = names & all_templates
                if dup:
                    self.err("E_DUPLICATE", K, wname, base, f"template names reused: {sorted(dup)}")
                all_templates |= names
                templates_by_state[sname] = names
            for i, region in enumerate(w.parallel):
                base = f"spec.parallel[{i}]"
                self._check_event(wname, f"{base}.on", region.on, w, None, set())
                self.ref(K, wname, f"{base}.join_at", "state", region.join_at, states)
                self._check_template(wname, f"{base}.start", region.start, role, seats_for_role, participants)
                if region.join_guard:
                    self._check_expr(K, wname, f"{base}.join_guard", region.join_guard, attrs, states)
                all_templates.add(region.start.template)

            graph: dict[str, set[str]] = {s: set() for s in states}
            used_emits: set[str] = set()
            for i, t in enumerate(w.transitions):
                base = f"spec.transitions[{i}]"
                ok = self.ref(K, wname, f"{base}.from", "state", t.from_, states)
                ok &= self.ref(K, wname, f"{base}.to", "state", t.to, states)
                if ok:
                    graph[t.from_].add(t.to)
                    if w.states[t.from_].final:
                        self.err("E_FINAL", K, wname, base, f"final state {t.from_!r} cannot have transitions")
                for ev in t.events:
                    self._check_event(wname, f"{base}.on", ev, w, t, templates_by_state.get(t.from_, set()))
                    if ev.startswith("timer."):
                        used_emits.add(ev.removeprefix("timer."))
                if t.by and not any(e.startswith("decision.") for e in t.events):
                    self.warn("W_BY", K, wname, f"{base}.by", "'by' only applies to decision events")
                if t.guard:
                    self._check_expr(K, wname, f"{base}.guard", t.guard, attrs, states)
                for j, eff in enumerate(t.effects):
                    for key, val in eff.items():
                        p = f"{base}.effects[{j}].{key}"
                        if key not in EFFECT_KEYS:
                            self.err("E_EFFECT", K, wname, p, f"unknown effect {key!r}; known {sorted(EFFECT_KEYS)}")
                        elif key == "start_timer" and val not in w.timers:
                            self.err("E_REF", K, wname, p, f"no timer {val!r}")
                        elif key == "lock" and val not in self.artifacts:
                            self.err("E_REF", K, wname, p, f"no artifact type {val!r}")
                        elif key == "handover" and val not in participants:
                            self.err("E_REF", K, wname, p, f"{val!r} is not a participant")
            for tname, timer in w.timers.items():
                if timer.emits not in used_emits:
                    self.warn("W_UNUSED_TIMER", K, wname, f"spec.timers.{tname}",
                              f"no transition listens for timer.{timer.emits}")

            if w.initial in states:
                seen, queue = {w.initial}, deque([w.initial])
                while queue:
                    for nxt in graph[queue.popleft()]:
                        if nxt not in seen:
                            seen.add(nxt)
                            queue.append(nxt)
                for s in sorted(states - seen):
                    self.err("E_UNREACHABLE", K, wname, f"spec.states.{s}", f"state {s!r} cannot be reached from {w.initial!r}")
                if not any(w.states[s].final for s in seen):
                    self.err("E_NO_FINAL", K, wname, "spec.states", "no final state is reachable")
                for s in sorted(seen):
                    if not w.states[s].final and not graph[s]:
                        self.err("E_DEAD_END", K, wname, f"spec.states.{s}", f"state {s!r} has no way out")
            self._check_decisions(wname, w, attrs, participants)

    def _check_decisions(self, wname: str, w, attrs: set[str], participants: set[str]) -> None:
        K = "WorkflowDefinition"
        for dname, dec in w.decisions.items():
            base = f"spec.decisions.{dname}"
            if dec.state not in w.states:
                self.err("E_REF", K, wname, f"{base}.state", f"no state {dec.state!r}")
                continue
            st = w.states[dec.state]
            if not st.view:
                self.err("E_DECISION", K, wname, base, f"state {dec.state!r} needs a view for decisions")
            if dec.for_ not in participants:
                self.err("E_REF", K, wname, f"{base}.for", f"{dec.for_!r} is not a participant")
            for attr_key, setter in dec.sets.items():
                if attr_key not in attrs:
                    self.err("E_REF", K, wname, f"{base}.sets.{attr_key}", f"{attr_key!r} is not a declared attribute")
                if setter not in ("artifact_version", "selection_count"):
                    self.err("E_DECISION", K, wname, f"{base}.sets.{attr_key}", f"unknown setter {setter!r}")
                if setter == "selection_count" and not dec.selection:
                    self.err(
                        "E_DECISION",
                        K,
                        wname,
                        f"{base}.sets.{attr_key}",
                        "selection_count setter requires selection: true",
                    )
            ev = f"decision.{dname}"
            matched = False
            for i, tr in enumerate(w.transitions):
                if tr.from_ != dec.state:
                    continue
                if ev not in tr.events:
                    continue
                if tr.by != dec.for_:
                    self.err(
                        "E_DECISION",
                        K,
                        wname,
                        f"spec.transitions[{i}]",
                        f"{ev!r} must have by={dec.for_!r}, not {tr.by!r}",
                    )
                matched = True
                break
            if not matched:
                self.err(
                    "E_DECISION",
                    K,
                    wname,
                    base,
                    f"no transition from {dec.state!r} on {ev!r} with by={dec.for_!r}",
                )

    def _check_event(self, wname: str, path: str, ev: str, w, t, from_templates: set[str]) -> None:
        K = "WorkflowDefinition"
        prefix, _, rest = ev.partition(".")
        if prefix == "decision":
            if t is not None and not t.by:
                self.err("E_EVENT", K, wname, path, f"decision event {ev!r} needs 'by' (who decides)")
            elif t is not None and t.by not in w.participants:
                self.err("E_REF", K, wname, path, f"{t.by!r} is not a participant")
        elif prefix == "task" and rest.startswith("completed."):
            tmpl = rest.removeprefix("completed.")
            if tmpl not in from_templates:
                self.err("E_EVENT", K, wname, path, f"{ev!r}: state does not create template {tmpl!r}")
        elif prefix == "timer":
            if rest not in {tm.emits for tm in w.timers.values()}:
                self.err("E_EVENT", K, wname, path, f"{ev!r}: no timer emits {rest!r}")
        elif prefix == "event":
            if rest not in w.events:
                self.err("E_EVENT", K, wname, path, f"{ev!r}: {rest!r} is not declared in spec.events")
        else:
            self.err("E_EVENT", K, wname, path,
                     f"{ev!r}: events are decision.*, task.completed.*, timer.* or event.*")

    def check_evals(self) -> None:
        for name, e in self.evals.items():
            s = e.spec
            for i, t in enumerate(s.targets):
                self.ref("EvalSuite", name, f"spec.targets[{i}]", "Seat", t, self.seats)
            if self.ref("EvalSuite", name, "spec.workflow", "WorkflowDefinition", s.workflow, self.workflows):
                w = self.workflows[s.workflow].spec
                if s.at_state and s.at_state not in w.states:
                    self.err("E_REF", "EvalSuite", name, "spec.at_state", f"no state {s.at_state!r}")
                if s.as_participant and s.as_participant not in w.participants:
                    self.err("E_REF", "EvalSuite", name, "spec.as_participant", f"no participant {s.as_participant!r}")
            if s.script:
                folder = PurePosixPath(self.p.files[("EvalSuite", name)]).parent
                if (folder / s.script).as_posix() not in self.p.support_files:
                    self.err("E_FILE", "EvalSuite", name, "spec.script", f"script {s.script!r} not found")

    def check_effect_governance(self) -> None:
        """Every committed-effect tool a supervised Seat can reach must need an approval chain."""
        rules_by_action = {}
        for pol in self.policies.values():
            for r in pol.spec.rules:
                rules_by_action.setdefault(r.action, []).append(r)
        for sname, seat in self.seats.items():
            prof = self.policies.get(seat.spec.authority_profile.partition("@")[0])
            if prof is None or prof.spec.type != "authority_profile":
                continue
            for tname, (_, tool) in self.tools.items():
                if tool.tool_class != "committed_effect" or tool.resource not in seat.spec.resources:
                    continue
                action = f"{tool.resource}.{tool.action}"
                effects = {g.effect for g in prof.spec.grants
                           if g.resource == tool.resource and tool.action in g.actions}
                if "ALLOW" in effects and seat.spec.autonomy_mode == "supervised":
                    self.err("E_UNGOVERNED_EFFECT", "Seat", sname, "spec.authority_profile",
                             f"supervised Seat may {action} via {tname!r} without approval")
                if "REQUIRE_APPROVAL" in effects and not any(
                        r.effect == "REQUIRE_APPROVAL" for r in rules_by_action.get(action, [])):
                    self.err("E_NO_APPROVAL_CHAIN", "Seat", sname, "spec.authority_profile",
                             f"{action} requires approval but no gate rule names who approves")

    def check_manifest(self) -> None:
        m = self.p.manifest
        if not m:
            return
        all_states = {s for w in self.workflows.values() for s in w.spec.states}
        for st in m.spec.observability.stage_targets:
            if st not in all_states:
                self.issues.append(Issue("E_REF", "pack.yaml", f"spec.observability.stage_targets.{st}",
                                         f"no workflow has state {st!r}"))

    def check_owners(self) -> None:
        if not self.org:
            return
        owners = set(self.org.get("people", {})) | set(self.org.get("owner_roles", []))
        for (kind, name), _ in self.p.files.items():
            obj = self.p.objects[kind][name]
            if obj.metadata.owner not in owners:
                self.err("E_OWNER", kind, name, "metadata.owner",
                         f"owner {obj.metadata.owner!r} is not a person or owner role in the organization")
        teams = {f"{d}/{t}" for d, dept in self.org.get("departments", {}).items() for t in dept.get("teams", {})}
        for sname, seat in self.seats.items():
            if seat.spec.placement not in teams:
                self.err("E_PLACEMENT", "Seat", sname, "spec.placement", f"no team {seat.spec.placement!r}")


def validate_pack(root, org: dict | None = None) -> ValidationReport:
    pack = load_pack(root)
    issues = list(pack.issues)
    if not any(i.code in ("E_PACK_MISSING",) for i in issues):
        issues += _Checker(pack, org).run()
    m = pack.manifest
    counts = {kind: pack.count(kind) for kind in
              ("Role", "Resource", "ArtifactType", "Seat", "Skill", "Verifier", "ToolProvider", "Policy",
               "WorkflowDefinition", "EvalSuite")}
    counts["files"] = len(pack.files) + len(pack.support_files) + (1 if m else 0)
    return ValidationReport(pack=m.metadata.name if m else str(root), version=m.metadata.version if m else None,
                            digest=pack.digest, issues=issues, counts=counts)
