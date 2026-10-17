from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Issue:
    code: str
    file: str
    path: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        where = f"{self.file}:{self.path}" if self.path else self.file
        return f"{self.severity.upper():7} {self.code:22} {where}  {self.message}"


@dataclass
class ValidationReport:
    pack: str
    version: int | None
    digest: str
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def to_dict(self) -> dict:
        return {
            "pack": self.pack,
            "version": self.version,
            "digest": self.digest,
            "ok": self.ok,
            "counts": self.counts,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
        }
