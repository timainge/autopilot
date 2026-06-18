from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.errors import InvalidTransition, ValidationError
from autopilot.domain.persists import atomic_write, persists


@dataclass
class Enquiry:
    id: str
    iteration: int
    question: str
    status: Literal["pending", "active", "completed", "failed"] = "pending"
    findings: str = ""
    sources: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str | None = None
    _path: Path | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError(
                entity_type="enquiry", entity_id=None, field="id", reason="enquiry.id required"
            )
        if not self.question:
            raise ValidationError(
                entity_type="enquiry",
                entity_id=self.id,
                field="question",
                reason="enquiry.question required",
            )
        if self.iteration < 1:
            raise ValidationError(
                entity_type="enquiry",
                entity_id=self.id,
                field="iteration",
                reason="enquiry.iteration must be >= 1",
            )

    @persists
    def start(self) -> None:
        if self.status != "pending":
            raise InvalidTransition(
                entity_type="enquiry",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="start",
            )
        self.status = "active"

    @persists
    def complete(self, findings: str, sources: list[str], cost_usd: float) -> None:
        if self.status != "active":
            raise InvalidTransition(
                entity_type="enquiry",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition="complete",
            )
        self.status = "completed"
        self.findings = findings
        self.sources = list(sources)
        self.cost_usd = cost_usd

    @persists
    def fail(self, error: str) -> None:
        self.status = "failed"
        self.error = error

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="enquiry",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "iteration": self.iteration,
            "status": self.status,
            "question": self.question,
            "sources": list(self.sources),
            "cost_usd": self.cost_usd,
            "error": self.error,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.findings}\n"
        atomic_write(self._path, content)


_RUN_STATUS = (
    "planning",
    "executing",
    "synthesising",
    "evaluating",
    "satisfied",
    "capped",
    "stopped",
)


@dataclass
class ResearchRun:
    slug: str
    brief: str
    status: Literal[
        "planning", "executing", "synthesising", "evaluating", "satisfied", "capped", "stopped"
    ] = "planning"
    iteration: int = 0
    enquiries: list[Enquiry] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    summary: str | None = None
    cost_usd: float = 0.0
    _dir: Path | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValidationError(
                entity_type="research_run",
                entity_id=None,
                field="slug",
                reason="research_run.slug required",
            )
        if not self.brief:
            raise ValidationError(
                entity_type="research_run",
                entity_id=self.slug,
                field="brief",
                reason="research_run.brief required",
            )

    @persists
    def start_iteration(self) -> None:
        if self.status not in ("planning", "evaluating"):
            raise InvalidTransition(
                entity_type="research_run",
                entity_id=self.slug,
                current_status=self.status,
                attempted_transition="start_iteration",
            )
        self.status = "executing"
        self.iteration += 1

    @persists
    def record_enquiries(self, new: list[Enquiry]) -> None:
        self.enquiries.extend(new)

    @persists
    def mark_synthesising(self) -> None:
        if self.status != "executing":
            raise InvalidTransition(
                entity_type="research_run",
                entity_id=self.slug,
                current_status=self.status,
                attempted_transition="mark_synthesising",
            )
        self.status = "synthesising"

    @persists
    def mark_evaluating(self) -> None:
        if self.status != "synthesising":
            raise InvalidTransition(
                entity_type="research_run",
                entity_id=self.slug,
                current_status=self.status,
                attempted_transition="mark_evaluating",
            )
        self.status = "evaluating"

    @persists
    def record_coverage(self, gaps: list[str]) -> None:
        self.gaps = list(gaps)

    @persists
    def satisfy(self, summary: str) -> None:
        if self.status != "evaluating":
            raise InvalidTransition(
                entity_type="research_run",
                entity_id=self.slug,
                current_status=self.status,
                attempted_transition="satisfy",
            )
        if not summary:
            raise ValidationError(
                entity_type="research_run",
                entity_id=self.slug,
                field="summary",
                reason="satisfy requires summary",
            )
        self.status = "satisfied"
        self.summary = summary

    @persists
    def cap(self, summary: str) -> None:
        if not summary:
            raise ValidationError(
                entity_type="research_run",
                entity_id=self.slug,
                field="summary",
                reason="cap requires summary",
            )
        self.status = "capped"
        self.summary = summary

    @persists
    def stop(self, reason: str) -> None:
        self.status = "stopped"
        self.summary = reason

    @classmethod
    def load(cls, run_dir: Path) -> "ResearchRun":
        from autopilot.domain.parse import parse_research_run

        run_path = run_dir / "run.md"
        text = run_path.read_text(encoding="utf-8")
        run = parse_research_run(text, path=run_path)
        run._dir = run_dir
        enquiries: list[Enquiry] = []
        for ep in sorted(run_dir.glob("enquiry-*.md")):
            from autopilot.domain.parse import parse_enquiry

            enq = parse_enquiry(ep.read_text(encoding="utf-8"), path=ep)
            enq._path = ep
            enquiries.append(enq)
        run.enquiries = enquiries
        return run

    def _save(self) -> None:
        if self._dir is None:
            raise ValidationError(
                entity_type="research_run",
                entity_id=self.slug,
                field="_dir",
                reason="_dir must be set before _save()",
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        fm: dict[str, Any] = {
            "slug": self.slug,
            "status": self.status,
            "iteration": self.iteration,
            "gaps": list(self.gaps),
            "summary": self.summary,
            "cost_usd": self.cost_usd,
        }
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{self.brief}\n"
        atomic_write(self._dir / "run.md", content)
