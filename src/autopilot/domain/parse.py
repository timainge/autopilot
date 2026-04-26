"""Agent text → entity parsers. Per design §6.5 / §12.9: strict, fail-fast."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from autopilot.domain.errors import ParseError
from autopilot.domain.eval import Eval
from autopilot.domain.goal import Goal
from autopilot.domain.ids import EvalRef, EvalRunId, SprintId
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import RevisionRecord, Sprint
from autopilot.domain.task import AttemptRecord, Task

# Per-entity allow-lists (§12.9 strict parsing). Unknown top-level keys → ParseError.
_ROADMAP_KEYS = {"archetype", "eval"}
_GOAL_KEYS = {"id", "priority", "status", "eval", "achieved_by", "summary"}
_SPRINT_KEYS = {
    "id",
    "primary_goal",
    "status",
    "revision_rounds",
    "summary",
    "closing_evaluator_notes",
}
_TASK_KEYS = {"id", "status", "depends_on", "eval", "attempts", "summary"}
_EVAL_RUN_KEYS = {
    "id",
    "eval_ref",
    "eval_snapshot",
    "started_at",
    "completed_at",
    "status",
    "score",
    "output",
    "cost_usd",
    "context_digest",
}


@dataclass
class JudgeVerdict:
    ready: bool
    feedback: str


# ---------- shared helpers ----------


def _split_frontmatter(text: str, path: Path | None = None) -> tuple[dict[str, Any], str]:
    """Parse a `---\\nYAML\\n---\\n\\nBODY` document. Returns (frontmatter_dict, body)."""
    fp = path if path is not None else Path("<memory>")
    if not text.startswith("---"):
        raise ParseError(
            file_path=fp, line_number=1, reason="file must start with '---' frontmatter fence"
        )
    # Locate closing fence. Tolerate either leading or no leading blank line before YAML.
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("---"):
        raise ParseError(file_path=fp, line_number=1, reason="missing opening '---'")
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == "---":
            close_idx = i
            break
    if close_idx is None:
        raise ParseError(file_path=fp, line_number=None, reason="missing closing '---'")
    yaml_text = "".join(lines[1:close_idx])
    body_lines = lines[close_idx + 1 :]
    # Trim one leading blank line from the body if present.
    if body_lines and body_lines[0].strip() == "":
        body_lines = body_lines[1:]
    body = "".join(body_lines)
    # Strip trailing newlines so re-serialisation (which appends "\n") round-trips.
    body = body.rstrip("\n")
    try:
        fm = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise ParseError(file_path=fp, line_number=None, reason=f"yaml error: {e}") from e
    if not isinstance(fm, dict):
        raise ParseError(
            file_path=fp, line_number=None, reason="frontmatter must be a YAML mapping"
        )
    return fm, body


def _check_keys(fm: dict[str, Any], allowed: set[str], path: Path | None) -> None:
    fp = path if path is not None else Path("<memory>")
    for k in fm:
        if k not in allowed:
            raise ParseError(file_path=fp, line_number=None, reason=f"unknown frontmatter key: {k}")


def _require(fm: dict[str, Any], key: str, path: Path | None) -> Any:
    if key not in fm:
        fp = path if path is not None else Path("<memory>")
        raise ParseError(
            file_path=fp, line_number=None, reason=f"missing required frontmatter key: {key}"
        )
    return fm[key]


def _parse_dt(v: Any, path: Path | None, field: str) -> datetime:
    fp = path if path is not None else Path("<memory>")
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        raise ParseError(
            file_path=fp,
            line_number=None,
            reason=f"{field}: expected ISO-8601 string, got {type(v).__name__}",
        )
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ParseError(
            file_path=fp, line_number=None, reason=f"{field}: invalid ISO-8601: {v}"
        ) from e


def _parse_dt_opt(v: Any, path: Path | None, field: str) -> datetime | None:
    if v is None:
        return None
    return _parse_dt(v, path, field)


def _parse_evals(raw: Any, path: Path | None) -> list[Eval]:
    fp = path if path is not None else Path("<memory>")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ParseError(file_path=fp, line_number=None, reason="eval: expected list")
    out: list[Eval] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ParseError(file_path=fp, line_number=None, reason=f"eval[{i}]: expected mapping")
        out.append(Eval.from_dict(d))
    return out


def _parse_attempts(raw: Any, path: Path | None) -> list[AttemptRecord]:
    fp = path if path is not None else Path("<memory>")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ParseError(file_path=fp, line_number=None, reason="attempts: expected list")
    out: list[AttemptRecord] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ParseError(
                file_path=fp, line_number=None, reason=f"attempts[{i}]: expected mapping"
            )
        out.append(
            AttemptRecord(
                started_at=_parse_dt_opt(d.get("started_at"), fp, f"attempts[{i}].started_at"),
                completed_at=_parse_dt_opt(
                    d.get("completed_at"), fp, f"attempts[{i}].completed_at"
                ),
                failed_at=_parse_dt_opt(d.get("failed_at"), fp, f"attempts[{i}].failed_at"),
                error=d.get("error"),
            )
        )
    return out


def _parse_revision_rounds(raw: Any, path: Path | None) -> list[RevisionRecord]:
    fp = path if path is not None else Path("<memory>")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ParseError(file_path=fp, line_number=None, reason="revision_rounds: expected list")
    out: list[RevisionRecord] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ParseError(
                file_path=fp,
                line_number=None,
                reason=f"revision_rounds[{i}]: expected mapping",
            )
        ts = d.get("timestamp")
        out.append(
            RevisionRecord(
                critic_notes=d.get("critic_notes", ""),
                judge_verdict=d.get("judge_verdict", ""),
                feedback=d.get("feedback", "") or "",
                timestamp=_parse_dt_opt(ts, fp, f"revision_rounds[{i}].timestamp"),
            )
        )
    return out


# ---------- public parsers ----------


def parse_task(text: str, sprint_id: str | None = None, path: Path | None = None) -> Task:
    """Parse a task file. sprint_id is reserved for cross-refs; not currently stored."""
    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _TASK_KEYS, path)
    task_id = _require(fm, "id", path)
    _require(fm, "status", path)
    if not body.strip():
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="task body (intent) is required")
    return Task(
        id=str(task_id),
        intent=body,
        status=fm["status"],
        depends_on=list(fm.get("depends_on") or []),
        eval=_parse_evals(fm.get("eval"), path),
        attempts=_parse_attempts(fm.get("attempts"), path),
        summary=fm.get("summary"),
    )


def parse_goal(text: str, path: Path | None = None) -> Goal:
    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _GOAL_KEYS, path)
    goal_id = _require(fm, "id", path)
    priority = _require(fm, "priority", path)
    if not isinstance(priority, int) or isinstance(priority, bool):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="priority: expected int")
    if not body.strip():
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="goal body (intent) is required")
    achieved_by_raw = fm.get("achieved_by") or []
    achieved_by: list[SprintId] = [SprintId(str(s)) for s in achieved_by_raw]
    return Goal(
        id=str(goal_id),
        intent=body,
        priority=priority,
        status=fm.get("status", "pending"),
        eval=_parse_evals(fm.get("eval"), path),
        achieved_by=achieved_by,
        summary=fm.get("summary"),
    )


def parse_roadmap(text: str, path: Path | None = None) -> Roadmap:
    """Parse roadmap frontmatter + narrative. Goals are loaded separately by the harness."""
    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _ROADMAP_KEYS, path)
    archetype = _require(fm, "archetype", path)
    return Roadmap(
        archetype=str(archetype),
        eval=_parse_evals(fm.get("eval"), path),
        narrative=body,
        goals=[],
    )


def parse_sprint(
    sprint_text: str,
    task_texts: list[str],
    sprint_path: Path | None = None,
    task_paths: list[Path] | None = None,
    *,
    expected_id: str | None = None,
    expected_primary_goal: str | None = None,
) -> Sprint:
    # Orchestrator is authoritative for sprint id and primary_goal; planner
    # frontmatter is a hint, overridable at parse time so the final Sprint is
    # constructed with the authoritative values (§5: validate on mutate — no
    # post-construction patching of required fields).
    fm, body = _split_frontmatter(sprint_text, sprint_path)
    _check_keys(fm, _SPRINT_KEYS, sprint_path)
    fm_sprint_id = _require(fm, "id", sprint_path)
    fm_primary_goal = _require(fm, "primary_goal", sprint_path)
    _require(fm, "status", sprint_path)
    sprint_id = expected_id if expected_id is not None else str(fm_sprint_id)
    primary_goal = (
        expected_primary_goal if expected_primary_goal is not None else str(fm_primary_goal)
    )
    if task_paths is not None and len(task_paths) != len(task_texts):
        raise ValueError("task_paths length must match task_texts length")
    tasks: list[Task] = []
    for i, t_text in enumerate(task_texts):
        tp = task_paths[i] if task_paths else None
        tasks.append(parse_task(t_text, sprint_id=sprint_id, path=tp))
    return Sprint(
        id=sprint_id,
        primary_goal=primary_goal,
        context=body,
        tasks=tasks,
        status=fm["status"],
        revision_rounds=_parse_revision_rounds(fm.get("revision_rounds"), sprint_path),
        summary=fm.get("summary"),
        closing_evaluator_notes=fm.get("closing_evaluator_notes"),
    )


def parse_verdict(text: str) -> JudgeVerdict:
    """Per design §9 judge verdict regex.

    `VERDICT: READY` present AND `VERDICT: NOT_READY` absent → ready=True.
    Feedback = full body with verdict marker line stripped.
    """
    ready = ("VERDICT: READY" in text) and ("VERDICT: NOT_READY" not in text)
    feedback_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in ("VERDICT: READY", "VERDICT: NOT_READY"):
            continue
        feedback_lines.append(line)
    feedback = "\n".join(feedback_lines).strip()
    return JudgeVerdict(ready=ready, feedback=feedback)


def parse_eval_run(text: str, path: Path | None = None):  # noqa: ANN201 — imported lazily
    """Parse an eval-run file. Returns EvalRun."""
    # Local import to keep parse.py's import set flat and avoid any circularity via eval.py.
    from autopilot.domain.eval import EvalRun

    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _EVAL_RUN_KEYS, path)
    run_id = _require(fm, "id", path)
    ref_raw = _require(fm, "eval_ref", path)
    if not isinstance(ref_raw, dict):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="eval_ref: expected mapping")
    ref = EvalRef(
        entity_type=ref_raw["entity_type"],
        entity_id=str(ref_raw["entity_id"]),
        eval_index=int(ref_raw["eval_index"]),
    )
    started_at = _parse_dt(_require(fm, "started_at", path), path, "started_at")
    completed_at = _parse_dt_opt(fm.get("completed_at"), path, "completed_at")
    snapshot = fm.get("eval_snapshot") or {}
    if not isinstance(snapshot, dict):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="eval_snapshot: expected mapping")
    # Body is the fenced output block; extract it back out so round-trip is byte-exact.
    output = _extract_eval_run_output(body)
    return EvalRun(
        id=EvalRunId(str(run_id)),
        eval_ref=ref,
        eval_snapshot=dict(snapshot),
        started_at=started_at,
        completed_at=completed_at,
        status=fm.get("status", "running"),
        score=fm.get("score"),
        output=output,
        cost_usd=float(fm.get("cost_usd", 0.0)),
        context_digest=str(fm.get("context_digest", "")),
    )


def _extract_eval_run_output(body: str) -> str:
    """Inverse of EvalRun._save body format: '# EvalRun <id>\\n\\n```\\n<output>\\n```'."""
    lines = body.splitlines()
    # Find first fence after the heading.
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "```")
    except StopIteration:
        return ""
    try:
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "```")
    except StopIteration:
        return ""
    return "\n".join(lines[start + 1 : end])
