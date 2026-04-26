from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.persists import atomic_write, persists
from autopilot.domain.task import Task


@dataclass
class RevisionRecord:
    critic_notes: str
    judge_verdict: str
    feedback: str = ""
    timestamp: datetime | None = None


@dataclass
class Sprint:
    id: str
    primary_goal: str
    context: str
    tasks: list[Task]
    status: Literal["planning", "approved", "active", "completed", "failed", "escalated"]
    revision_rounds: list[RevisionRecord] = field(default_factory=list)
    summary: str | None = None
    # Evaluator's prose verdict when the sprint completed but the goal was
    # judged not yet met. Surfaced to the next planner so the remediation
    # sprint sees what the prior pass missed.
    closing_evaluator_notes: str | None = None
    _dir: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="sprint", entity_id=None, field="id", reason="sprint.id required"
            )
        if not self.primary_goal:
            raise ValidationError(
                entity_type="sprint",
                entity_id=self.id,
                field="primary_goal",
                reason="sprint.primary_goal required",
            )
        if not self.tasks:
            raise ValidationError(
                entity_type="sprint",
                entity_id=self.id,
                field="tasks",
                reason="sprint must have at least one task",
            )
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValidationError(
                entity_type="sprint",
                entity_id=self.id,
                field="tasks",
                reason="duplicate task ids",
            )

    @persists
    def approve(self) -> None:
        if self.status != "planning":
            raise InvalidTransition(
                entity_type="sprint",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="approve",
            )
        self.status = "approved"

    @persists
    def start(self) -> None:
        if self.status != "approved":
            raise InvalidTransition(
                entity_type="sprint",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="start",
            )
        self.status = "active"

    @persists
    def complete(self, summary: str) -> None:
        if self.status != "active":
            raise InvalidTransition(
                entity_type="sprint",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="complete",
            )
        if any(t.status != "completed" for t in self.tasks):
            raise InvalidTransition(
                entity_type="sprint",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="complete (non-completed tasks remain)",
            )
        if not summary:
            raise ValidationError(
                entity_type="sprint",
                entity_id=self.id,
                field="summary",
                reason="complete requires summary",
            )
        self.status = "completed"
        self.summary = summary

    @persists
    def fail(self, summary: str) -> None:
        self.status = "failed"
        self.summary = summary

    @persists
    def escalate(self, reason: str) -> None:
        self.status = "escalated"
        self.summary = reason

    @persists
    def set_closing_evaluator_notes(self, text: str) -> None:
        """Persist evaluator feedback after a sprint that didn't achieve its goal."""
        self.closing_evaluator_notes = text

    @classmethod
    def load(cls, sprint_dir: Path) -> "Sprint":
        from autopilot.domain.parse import parse_sprint

        sprint_path = sprint_dir / f"{sprint_dir.name}.md"
        sprint_text = sprint_path.read_text(encoding="utf-8")
        task_paths = sorted(sprint_dir.glob("task-*.md"))
        task_texts = [p.read_text(encoding="utf-8") for p in task_paths]
        sprint = parse_sprint(
            sprint_text, task_texts, sprint_path=sprint_path, task_paths=task_paths
        )
        sprint._dir = sprint_dir
        for task, tp in zip(sprint.tasks, task_paths, strict=True):
            task._path = tp
        return sprint

    def _save(self) -> None:
        if self._dir is None:
            raise ValidationError(
                entity_type="sprint",
                entity_id=self.id,
                field="_dir",
                reason="_dir must be set before _save()",
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        fm: dict[str, Any] = {
            "id": self.id,
            "primary_goal": self.primary_goal,
            "status": self.status,
            "revision_rounds": [_revision_to_dict(r) for r in self.revision_rounds],
            "summary": self.summary,
            "closing_evaluator_notes": self.closing_evaluator_notes,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.context}\n"
        atomic_write(self._dir / f"{self.id}.md", content)


def _iso(dt: datetime) -> str:
    s = dt.isoformat()
    if s.endswith("+00:00"):
        s = s[: -len("+00:00")] + "Z"
    return s


def _revision_to_dict(r: RevisionRecord) -> dict[str, Any]:
    out: dict[str, Any] = {
        "critic_notes": r.critic_notes,
        "judge_verdict": r.judge_verdict,
    }
    if r.feedback:
        out["feedback"] = r.feedback
    if r.timestamp is not None:
        out["timestamp"] = _iso(r.timestamp)
    return out
