from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from autopilot.domain.errors import ValidationError
from autopilot.domain.eval import Eval
from autopilot.domain.goal import Goal
from autopilot.domain.persists import atomic_write


@dataclass
class Roadmap:
    archetype: str
    eval: list[Eval]
    narrative: str
    goals: list[Goal] = field(default_factory=list)
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.archetype:
            raise ValidationError(
                entity_type="roadmap",
                entity_id=None,
                field="archetype",
                reason="roadmap.archetype required",
            )
        ids = [g.id for g in self.goals]
        if len(set(ids)) != len(ids):
            raise ValidationError(
                entity_type="roadmap",
                entity_id=None,
                field="goals",
                reason="duplicate goal ids",
            )

    def next_pending_goal(self) -> Goal | None:
        for g in sorted(self.goals, key=lambda g: g.priority):
            if g.status in ("pending", "in-progress"):
                return g
        return None

    def goal(self, goal_id: str) -> Goal:
        for g in self.goals:
            if g.id == goal_id:
                return g
        raise ValidationError(
            entity_type="roadmap",
            entity_id=None,
            field="goal_id",
            reason=f"goal not found: {goal_id}",
        )

    @classmethod
    def load(cls, path: Path) -> "Roadmap":
        from autopilot.domain.parse import parse_roadmap

        text = path.read_text(encoding="utf-8")
        roadmap = parse_roadmap(text, path=path)
        goals_dir = path.parent / "goals"
        goals: list[Goal] = []
        if goals_dir.is_dir():
            for gp in sorted(goals_dir.glob("goal-*.md")):
                goals.append(Goal.load(gp))
        goals.sort(key=lambda g: g.priority)
        roadmap.goals = goals
        roadmap._path = path
        return roadmap

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="roadmap",
                entity_id=None,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "archetype": self.archetype,
            "eval": [e.to_dict() for e in self.eval],
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.narrative}\n"
        atomic_write(self._path, content)
