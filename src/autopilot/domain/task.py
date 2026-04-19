from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.clock import now
from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.eval import Eval
from autopilot.domain.persists import atomic_write, persists

# Per design §5.1: error strings truncated at 2000 chars before persisting.
_ERROR_TRUNCATE_CHARS = 2_000


@dataclass
class AttemptRecord:
    started_at: datetime | None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error: str | None = None


@dataclass
class Task:
    id: str
    intent: str
    status: Literal["pending", "active", "completed", "failed"] = "pending"
    depends_on: list[str] = field(default_factory=list)
    eval: list[Eval] = field(default_factory=list)
    attempts: list[AttemptRecord] = field(default_factory=list)
    summary: str | None = None
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="task", entity_id=None, field="id", reason="task.id required"
            )
        if not self.intent:
            raise ValidationError(
                entity_type="task",
                entity_id=self.id,
                field="intent",
                reason="task.intent required",
            )

    @persists
    def resume(self) -> None:
        """Reset an `active` task left over from a killed prior run to `pending`.

        Preserves the open attempt record. Only valid from `active` — other
        statuses raise `InvalidTransition`.
        """
        if self.status != "active":
            raise InvalidTransition(
                entity_type="task",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="resume",
            )
        self.status = "pending"

    @persists
    def start(self) -> None:
        match self.status:
            case "pending" | "failed":
                self.status = "active"
                self.attempts.append(AttemptRecord(started_at=now()))
            case _:
                raise InvalidTransition(
                    entity_type="task",
                    entity_id=self.id,
                    current_status=self.status,
                    attempted_transition="start",
                )

    @persists
    def complete(self, summary: str) -> None:
        if self.status != "active":
            raise InvalidTransition(
                entity_type="task",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="complete",
            )
        if not summary:
            raise ValidationError(
                entity_type="task",
                entity_id=self.id,
                field="summary",
                reason="complete requires summary",
            )
        self.status = "completed"
        self.summary = summary
        self.attempts[-1].completed_at = now()

    @persists
    def fail(self, error: str) -> None:
        if self.status not in ("active", "pending"):
            raise InvalidTransition(
                entity_type="task",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="fail",
            )
        if not error:
            raise ValidationError(
                entity_type="task",
                entity_id=self.id,
                field="error",
                reason="fail requires error",
            )
        truncated = _truncate(error, _ERROR_TRUNCATE_CHARS)
        self.status = "failed"
        if not self.attempts:
            # fail() from pending with no attempts: record a synthetic attempt.
            self.attempts.append(AttemptRecord(started_at=None))
        self.attempts[-1].error = truncated
        self.attempts[-1].failed_at = now()
        self.summary = truncated

    @classmethod
    def load(cls, path: Path) -> "Task":
        from autopilot.domain.parse import parse_task

        text = path.read_text(encoding="utf-8")
        task = parse_task(text, path=path)
        task._path = path
        return task

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="task",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "depends_on": list(self.depends_on),
            "status": self.status,
            "eval": [e.to_dict() for e in self.eval],
            "attempts": [_attempt_to_dict(a) for a in self.attempts],
            "summary": self.summary,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.intent}\n"
        atomic_write(self._path, content)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n]


def _iso(dt: datetime) -> str:
    s = dt.isoformat()
    if s.endswith("+00:00"):
        s = s[: -len("+00:00")] + "Z"
    return s


def _attempt_to_dict(a: AttemptRecord) -> dict[str, Any]:
    return {
        "started_at": _iso(a.started_at) if a.started_at else None,
        "completed_at": _iso(a.completed_at) if a.completed_at else None,
        "failed_at": _iso(a.failed_at) if a.failed_at else None,
        "error": a.error,
    }


def _attempt_from_dict(d: dict[str, Any]) -> AttemptRecord:
    def _parse(v: str | None) -> datetime | None:
        if v is None:
            return None
        # fromisoformat in 3.11 accepts trailing Z.
        return datetime.fromisoformat(v)

    return AttemptRecord(
        started_at=_parse(d.get("started_at")),
        completed_at=_parse(d.get("completed_at")),
        failed_at=_parse(d.get("failed_at")),
        error=d.get("error"),
    )
