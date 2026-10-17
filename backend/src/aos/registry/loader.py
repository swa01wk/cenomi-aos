"""Load a domain pack from a folder into typed kind objects.

Loading never stops at the first problem: every schema error is collected with its file and
path, so ``aos validate`` reports everything in one run.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .kinds import KINDS, Envelope, Pack
from .report import Issue


class PackYamlLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false are booleans.

    YAML 1.1 turns on/off/yes/no into booleans, so a transition's ``on:`` key would load as
    ``True``. Pack authors should never have to escape it.
    """


PackYamlLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
PackYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def parse_yaml(raw: bytes | str):
    return yaml.load(raw, Loader=PackYamlLoader)  # noqa: S506 - SafeLoader subclass


@dataclass
class LoadedPack:
    root: Path
    manifest: Pack | None = None
    # kind -> name -> object
    objects: dict[str, dict[str, Envelope]] = field(default_factory=dict)
    # (kind, name) -> relative file path
    files: dict[tuple[str, str], str] = field(default_factory=dict)
    # files that are not kinds (instructions, scripts): relative path -> sha256
    support_files: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    digest: str = ""

    def get(self, kind: str) -> dict[str, Envelope]:
        return self.objects.get(kind, {})

    def count(self, kind: str) -> int:
        return len(self.get(kind))


def _loc(err: dict) -> str:
    return ".".join(str(p) for p in err.get("loc", ()))


def load_pack(root: str | Path) -> LoadedPack:
    root = Path(root).resolve()
    pack = LoadedPack(root=root)
    if not root.is_dir():
        pack.issues.append(Issue("E_PACK_MISSING", str(root), "", "pack folder does not exist"))
        return pack

    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        raw = path.read_bytes()
        hasher.update(rel.encode() + b"\0" + raw)
        if path.suffix not in (".yaml", ".yml"):
            pack.support_files[rel] = hashlib.sha256(raw).hexdigest()
            continue
        try:
            doc = parse_yaml(raw)
        except yaml.YAMLError as exc:
            pack.issues.append(Issue("E_YAML", rel, "", f"not valid YAML: {exc}"))
            continue
        if not isinstance(doc, dict) or "apiVersion" not in doc:
            # A support file such as an eval script; checked by whoever references it.
            pack.support_files[rel] = hashlib.sha256(raw).hexdigest()
            continue
        kind = doc.get("kind")
        model = KINDS.get(kind)
        if model is None:
            pack.issues.append(Issue("E_KIND", rel, "kind", f"unknown kind {kind!r}; known: {sorted(KINDS)}"))
            continue
        try:
            obj = model.model_validate(doc)
        except ValidationError as exc:
            for err in exc.errors():
                pack.issues.append(Issue("E_SCHEMA", rel, _loc(err), err["msg"]))
            continue
        if isinstance(obj, Pack):
            if pack.manifest is not None:
                pack.issues.append(Issue("E_DUPLICATE", rel, "", "more than one Pack manifest"))
            pack.manifest = obj
            continue
        name = obj.metadata.name
        bucket = pack.objects.setdefault(kind, {})
        if name in bucket:
            pack.issues.append(Issue("E_DUPLICATE", rel, "metadata.name",
                                     f"{kind} {name!r} is also defined in {pack.files[(kind, name)]}"))
            continue
        bucket[name] = obj
        pack.files[(kind, name)] = rel

    if pack.manifest is None:
        pack.issues.append(Issue("E_MANIFEST", "pack.yaml", "", "the pack has no Pack manifest"))
    pack.digest = hasher.hexdigest()
    return pack
