from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.clock import now
from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.persists import atomic_write, persists


@dataclass
class Cell:
    id: str
    study_id: str
    params: dict[str, str]
    rep: int
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    signals: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="cell", entity_id=None, field="id", reason="cell.id required"
            )
        if not self.study_id:
            raise ValidationError(
                entity_type="cell",
                entity_id=self.id,
                field="study_id",
                reason="cell.study_id required",
            )
        if not isinstance(self.params, dict) or not self.params:
            raise ValidationError(
                entity_type="cell",
                entity_id=self.id,
                field="params",
                reason="cell.params must be a non-empty mapping",
            )
        if self.rep < 1:
            raise ValidationError(
                entity_type="cell",
                entity_id=self.id,
                field="rep",
                reason="cell.rep must be >= 1",
            )

    @persists
    def start(self) -> None:
        if self.status != "pending":
            raise InvalidTransition(
                entity_type="cell",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="start",
            )
        self.status = "running"
        self.started_at = now()

    @persists
    def complete(self, signals: dict[str, Any], cost_usd: float) -> None:
        if self.status != "running":
            raise InvalidTransition(
                entity_type="cell",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="complete",
            )
        if not isinstance(signals, dict):
            raise ValidationError(
                entity_type="cell",
                entity_id=self.id,
                field="signals",
                reason="signals must be a mapping",
            )
        self.status = "completed"
        self.signals = dict(signals)
        self.cost_usd = cost_usd
        self.completed_at = now()

    @persists
    def fail(self, error: str) -> None:
        if self.status not in ("pending", "running"):
            raise InvalidTransition(
                entity_type="cell",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="fail",
            )
        self.status = "failed"
        self.error = error
        self.completed_at = now()

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="cell",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "study_id": self.study_id,
            "params": dict(self.params),
            "rep": self.rep,
            "status": self.status,
            "signals": self.signals,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n# Cell {self.id}\n"
        atomic_write(self._path, content)


@dataclass
class Study:
    id: str
    objective: str
    matrix: dict[str, list[str]]
    run_cmd: str
    scorer_cmd: str
    repetitions: int = 1
    status: Literal["running", "completed", "stopped"] = "running"
    cells: list[Cell] = field(default_factory=list)
    summary: str | None = None
    cost_usd: float = 0.0
    _dir: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="study", entity_id=None, field="id", reason="study.id required"
            )
        if not self.objective:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="objective",
                reason="study.objective required",
            )
        if not isinstance(self.matrix, dict) or not self.matrix:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="matrix",
                reason="study.matrix must be a non-empty mapping",
            )
        for k, v in self.matrix.items():
            if not isinstance(v, list) or not v:
                raise ValidationError(
                    entity_type="study",
                    entity_id=self.id,
                    field="matrix",
                    reason=f"matrix.{k} must be a non-empty list",
                )
        if not self.run_cmd:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="run_cmd",
                reason="study.run_cmd required",
            )
        if not self.scorer_cmd:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="scorer_cmd",
                reason="study.scorer_cmd required",
            )
        if self.repetitions < 1:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="repetitions",
                reason="study.repetitions must be >= 1",
            )

    def _require_running(self, transition: str) -> None:
        if self.status != "running":
            raise InvalidTransition(
                entity_type="study",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition=transition,
            )

    @persists
    def add_cost(self, cost_usd: float) -> None:
        self.cost_usd += cost_usd

    @persists
    def resume(self) -> None:
        if self.status != "stopped":
            raise InvalidTransition(
                entity_type="study",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="resume",
            )
        self.status = "running"
        self.summary = None

    @persists
    def complete(self, summary: str) -> None:
        self._require_running("complete")
        if not summary:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="summary",
                reason="complete requires summary",
            )
        self.status = "completed"
        self.summary = summary

    @persists
    def stop(self, reason: str) -> None:
        self._require_running("stop")
        self.status = "stopped"
        self.summary = reason

    @classmethod
    def load(cls, study_dir: Path) -> "Study":
        from autopilot.domain.parse import parse_cell, parse_study

        study_path = study_dir / f"{study_dir.name}.md"
        study = parse_study(study_path.read_text(encoding="utf-8"), path=study_path)
        study._dir = study_dir
        cells: list[Cell] = []
        for cp in sorted(study_dir.glob("cell-*.md")):
            cell = parse_cell(cp.read_text(encoding="utf-8"), path=cp)
            cell._path = cp
            cells.append(cell)
        study.cells = cells
        return study

    def _save(self) -> None:
        if self._dir is None:
            raise ValidationError(
                entity_type="study",
                entity_id=self.id,
                field="_dir",
                reason="_dir must be set before _save()",
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        fm: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "matrix": {k: list(v) for k, v in self.matrix.items()},
            "repetitions": self.repetitions,
            "run": self.run_cmd,
            "scorer": self.scorer_cmd,
            "summary": self.summary,
            "cost_usd": self.cost_usd,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.objective}\n"
        atomic_write(self._dir / f"{self.id}.md", content)
