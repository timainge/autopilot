from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.eval import Eval
from autopilot.domain.ids import SprintId
from autopilot.domain.persists import atomic_write, persists


@dataclass
class Goal:
    id: str
    intent: str
    priority: int
    status: Literal["pending", "in-progress", "achieved"] = "pending"
    eval: list[Eval] = field(default_factory=list)
    achieved_by: list[SprintId] = field(default_factory=list)
    summary: str | None = None
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="goal", entity_id=None, field="id", reason="goal.id required"
            )
        if not self.intent:
            raise ValidationError(
                entity_type="goal",
                entity_id=self.id,
                field="intent",
                reason="goal.intent required",
            )

    @persists
    def mark_in_progress(self, sprint_id: SprintId) -> None:
        if self.status == "achieved":
            raise InvalidTransition(
                entity_type="goal",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="mark_in_progress",
            )
        self.status = "in-progress"
        if sprint_id not in self.achieved_by:
            self.achieved_by.append(sprint_id)

    @persists
    def mark_achieved(self, sprint_id: SprintId, summary: str) -> None:
        if self.status == "achieved":
            raise InvalidTransition(
                entity_type="goal",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="mark_achieved",
            )
        if not summary:
            raise ValidationError(
                entity_type="goal",
                entity_id=self.id,
                field="summary",
                reason="achievement requires summary",
            )
        self.status = "achieved"
        if sprint_id not in self.achieved_by:
            self.achieved_by.append(sprint_id)
        self.summary = summary

    @classmethod
    def load(cls, path: Path) -> "Goal":
        from autopilot.domain.parse import parse_goal

        text = path.read_text(encoding="utf-8")
        goal = parse_goal(text, path=path)
        goal._path = path
        return goal

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="goal",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "priority": self.priority,
            "status": self.status,
            "eval": [e.to_dict() for e in self.eval],
            "achieved_by": list(self.achieved_by),
            "summary": self.summary,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.intent}\n"
        atomic_write(self._path, content)
