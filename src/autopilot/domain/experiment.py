from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.clock import now
from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.persists import atomic_write, persists

_LAP_VERDICTS = ("merge", "discard", "iterate")


@dataclass
class Lap:
    id: str
    experiment_id: str
    spec: str
    branch: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    verdict: Literal["pending", "merge", "discard", "iterate"] = "pending"
    verdict_reason: str | None = None
    cost_usd: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="lap", entity_id=None, field="id", reason="lap.id required"
            )
        if not self.experiment_id:
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="experiment_id",
                reason="lap.experiment_id required",
            )
        if not self.spec:
            raise ValidationError(
                entity_type="lap", entity_id=self.id, field="spec", reason="lap.spec required"
            )
        if not isinstance(self.signals, dict):
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="signals",
                reason="lap.signals must be a mapping",
            )

    @persists
    def record(
        self, signals: dict[str, Any], verdict: str, reason: str, cost_usd: float
    ) -> None:
        if self.verdict != "pending":
            raise InvalidTransition(
                entity_type="lap",
                entity_id=self.id,
                current_status=self.verdict,
                attempted_transition="record",
            )
        if verdict not in _LAP_VERDICTS:
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="verdict",
                reason=f"verdict must be one of {_LAP_VERDICTS}, got {verdict!r}",
            )
        if not reason:
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="verdict_reason",
                reason="record requires a reason",
            )
        if not isinstance(signals, dict):
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="signals",
                reason="signals must be a mapping",
            )
        self.signals = dict(signals)
        self.verdict = verdict  # type: ignore[assignment]
        self.verdict_reason = reason
        self.cost_usd = cost_usd
        self.completed_at = now()

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="lap",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "branch": self.branch,
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "signals": self.signals,
            "cost_usd": self.cost_usd,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.spec}\n"
        atomic_write(self._path, content)


@dataclass
class Experiment:
    id: str
    mode: Literal["build", "tune", "research"]
    objective: str
    rubric: str
    hil_required: bool = False
    goal_id: str | None = None
    head_branch: str | None = None
    status: Literal["running", "completed", "stopped", "exhausted"] = "running"
    laps: list[Lap] = field(default_factory=list)
    summary: str | None = None
    cost_usd: float = 0.0
    _dir: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="experiment",
                entity_id=None,
                field="id",
                reason="experiment.id required",
            )
        if self.mode not in ("build", "tune", "research"):
            raise ValidationError(
                entity_type="experiment",
                entity_id=self.id,
                field="mode",
                reason=f"experiment.mode must be build|tune|research, got {self.mode!r}",
            )
        if not self.objective:
            raise ValidationError(
                entity_type="experiment",
                entity_id=self.id,
                field="objective",
                reason="experiment.objective required",
            )
        if not self.rubric:
            raise ValidationError(
                entity_type="experiment",
                entity_id=self.id,
                field="rubric",
                reason="experiment.rubric required",
            )

    def _require_running(self, transition: str) -> None:
        if self.status != "running":
            raise InvalidTransition(
                entity_type="experiment",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition=transition,
            )

    @persists
    def record_lap(self, lap: Lap) -> None:
        self._require_running("record_lap")
        self.laps.append(lap)

    @persists
    def add_cost(self, cost_usd: float) -> None:
        self.cost_usd += cost_usd

    @persists
    def complete(self, summary: str) -> None:
        self._require_running("complete")
        if not summary:
            raise ValidationError(
                entity_type="experiment",
                entity_id=self.id,
                field="summary",
                reason="complete requires summary",
            )
        self.status = "completed"
        self.summary = summary

    @persists
    def stop(self, summary: str) -> None:
        self._require_running("stop")
        self.status = "stopped"
        self.summary = summary

    @persists
    def exhaust(self, reason: str) -> None:
        self._require_running("exhaust")
        self.status = "exhausted"
        self.summary = reason

    @classmethod
    def load(cls, exp_dir: Path) -> "Experiment":
        from autopilot.domain.parse import parse_experiment, parse_lap

        exp_path = exp_dir / f"{exp_dir.name}.md"
        exp = parse_experiment(exp_path.read_text(encoding="utf-8"), path=exp_path)
        exp._dir = exp_dir
        laps: list[Lap] = []
        for lp in sorted(exp_dir.glob("lap-*.md")):
            if lp.name.endswith(".pending.md"):
                continue
            lap = parse_lap(lp.read_text(encoding="utf-8"), path=lp)
            lap._path = lp
            laps.append(lap)
        exp.laps = laps
        return exp

    def _save(self) -> None:
        if self._dir is None:
            raise ValidationError(
                entity_type="experiment",
                entity_id=self.id,
                field="_dir",
                reason="_dir must be set before _save()",
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        fm: dict[str, Any] = {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "rubric": self.rubric,
            "hil_required": self.hil_required,
            "goal_id": self.goal_id,
            "head_branch": self.head_branch,
            "summary": self.summary,
            "cost_usd": self.cost_usd,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.objective}\n"
        atomic_write(self._dir / f"{self.id}.md", content)
