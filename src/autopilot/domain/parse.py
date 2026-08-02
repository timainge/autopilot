"""Agent text → entity parsers. Per design §6.5 / §12.9: strict, fail-fast."""

import re
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
_RESEARCH_RUN_KEYS = {"slug", "status", "iteration", "gaps", "summary", "cost_usd"}
_ENQUIRY_KEYS = {"id", "iteration", "status", "question", "sources", "cost_usd", "error"}
_EXPERIMENT_KEYS = {
    "id",
    "mode",
    "status",
    "rubric",
    "hil_required",
    "goal_id",
    "head_branch",
    "summary",
    "cost_usd",
}
_LAP_KEYS = {
    "id",
    "experiment_id",
    "branch",
    "verdict",
    "verdict_reason",
    "signals",
    "cost_usd",
    "started_at",
    "completed_at",
}
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


def parse_research_run(text: str, path: Path | None = None):  # noqa: ANN201 — local import
    from autopilot.domain.research import ResearchRun

    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _RESEARCH_RUN_KEYS, path)
    slug = _require(fm, "slug", path)
    _require(fm, "status", path)
    if not body.strip():
        fp = path if path is not None else Path("<memory>")
        raise ParseError(
            file_path=fp, line_number=None, reason="research_run body (brief) is required"
        )
    iteration_raw = fm.get("iteration", 0)
    if not isinstance(iteration_raw, int) or isinstance(iteration_raw, bool):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="iteration: expected int")
    gaps_raw = fm.get("gaps") or []
    if not isinstance(gaps_raw, list):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="gaps: expected list")
    return ResearchRun(
        slug=str(slug),
        brief=body,
        status=fm["status"],
        iteration=iteration_raw,
        gaps=[str(g) for g in gaps_raw],
        summary=fm.get("summary"),
        cost_usd=float(fm.get("cost_usd", 0.0)),
    )


def parse_enquiry(text: str, path: Path | None = None):  # noqa: ANN201 — local import
    from autopilot.domain.research import Enquiry

    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _ENQUIRY_KEYS, path)
    enq_id = _require(fm, "id", path)
    iteration_raw = _require(fm, "iteration", path)
    _require(fm, "status", path)
    question = _require(fm, "question", path)
    if not isinstance(iteration_raw, int) or isinstance(iteration_raw, bool):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="iteration: expected int")
    sources_raw = fm.get("sources") or []
    if not isinstance(sources_raw, list):
        fp = path if path is not None else Path("<memory>")
        raise ParseError(file_path=fp, line_number=None, reason="sources: expected list")
    return Enquiry(
        id=str(enq_id),
        iteration=iteration_raw,
        question=str(question),
        status=fm["status"],
        findings=body,
        sources=[str(s) for s in sources_raw],
        cost_usd=float(fm.get("cost_usd", 0.0)),
        error=fm.get("error"),
    )


def _parse_enquiry_plan(
    text: str, *, starting_id: int, iteration: int, cap: int, path: Path | None = None
) -> list:
    """Decomposer output → list of Enquiry. Splits on `### ENQUIRY:` headers.

    Each envelope: header line `### ENQUIRY: <question>` followed by optional
    body lines (scope / context). Trailing prose outside any envelope → ParseError.
    The first ID equals `starting_id` (zero-padded width 3); subsequent ids increment.
    Caps the result at `cap` envelopes — extras are dropped silently (the
    decomposer prompt instructs no more than cap).
    """
    from autopilot.domain.research import Enquiry

    fp = path if path is not None else Path("<memory>")
    lines = text.splitlines()
    header_idxs: list[int] = []
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("### ENQUIRY:"):
            header_idxs.append(i)
    if not header_idxs:
        raise ParseError(
            file_path=fp,
            line_number=None,
            reason="decomposer output has no `### ENQUIRY:` envelope",
        )
    # Reject content before the first envelope (must be a clean enquiry list).
    pre = "\n".join(lines[: header_idxs[0]]).strip()
    if pre:
        raise ParseError(
            file_path=fp,
            line_number=None,
            reason="decomposer output: prose before first `### ENQUIRY:` envelope",
        )
    out: list[Enquiry] = []
    for n, hdr_idx in enumerate(header_idxs):
        if n >= cap:
            break
        end_idx = header_idxs[n + 1] if n + 1 < len(header_idxs) else len(lines)
        header = lines[hdr_idx]
        question = header.split(":", 1)[1].strip()
        body_lines = lines[hdr_idx + 1 : end_idx]
        body = "\n".join(body_lines).strip()
        full_question = question if not body else f"{question}\n\n{body}"
        if not full_question:
            raise ParseError(
                file_path=fp,
                line_number=None,
                reason=f"decomposer envelope {n}: empty question",
            )
        new_id = f"{starting_id + n:03d}"
        out.append(Enquiry(id=new_id, iteration=iteration, question=full_question))
    return out


def _parse_enquiry_output(text: str) -> tuple[str, list[str]]:
    """Researcher output → (findings, sources). Optional trailing `## Sources` section.

    `## Sources` is treated as the boundary. Findings = everything before;
    sources = bullet list under the heading (one per `- ` or `* ` line).
    No `## Sources` heading → returns the whole text as findings + `[]`.
    """
    lines = text.splitlines()
    boundary = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.lower() == "## sources":
            boundary = i
            break
    if boundary is None:
        return text.rstrip("\n"), []
    findings = "\n".join(lines[:boundary]).rstrip("\n")
    sources: list[str] = []
    for ln in lines[boundary + 1 :]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith(("- ", "* ")):
            sources.append(s[2:].strip())
        elif s.startswith("##"):  # next section
            break
    return findings, sources


@dataclass
class CoverageVerdict:
    satisfied: bool
    gaps: list[str]


def parse_coverage_verdict(text: str) -> CoverageVerdict:
    """Research-judge output: `COVERAGE: SATISFIED|INSUFFICIENT` + optional `## Gaps` list."""
    lines = text.splitlines()
    verdict_line = None
    for ln in lines:
        s = ln.strip()
        if s.startswith("COVERAGE:"):
            verdict_line = s
            break
    if verdict_line is None:
        raise ParseError(
            file_path=Path("<memory>"),
            line_number=None,
            reason="research-judge output missing `COVERAGE:` marker",
        )
    body = verdict_line.split(":", 1)[1].strip().upper()
    if body == "SATISFIED":
        satisfied = True
    elif body == "INSUFFICIENT":
        satisfied = False
    else:
        raise ParseError(
            file_path=Path("<memory>"),
            line_number=None,
            reason=f"research-judge: unknown verdict {body!r}",
        )
    gaps: list[str] = []
    in_gaps = False
    for ln in lines:
        s = ln.strip()
        if s.lower() == "## gaps":
            in_gaps = True
            continue
        if in_gaps:
            if s.startswith(("- ", "* ")):
                gaps.append(s[2:].strip())
            elif s.startswith("##"):
                break
    return CoverageVerdict(satisfied=satisfied, gaps=gaps)


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


# ---------- Frink (experiment loop) ----------


def parse_experiment(text: str, path: Path | None = None):  # noqa: ANN201 — local import
    from autopilot.domain.experiment import Experiment

    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _EXPERIMENT_KEYS, path)
    exp_id = _require(fm, "id", path)
    mode = _require(fm, "mode", path)
    _require(fm, "status", path)
    rubric = _require(fm, "rubric", path)
    fp = path if path is not None else Path("<memory>")
    if not body.strip():
        raise ParseError(
            file_path=fp, line_number=None, reason="experiment body (objective) is required"
        )
    hil_raw = fm.get("hil_required", False)
    if not isinstance(hil_raw, bool):
        raise ParseError(file_path=fp, line_number=None, reason="hil_required: expected bool")
    return Experiment(
        id=str(exp_id),
        mode=mode,
        objective=body,
        rubric=str(rubric),
        hil_required=hil_raw,
        goal_id=fm.get("goal_id"),
        head_branch=fm.get("head_branch"),
        status=fm["status"],
        summary=fm.get("summary"),
        cost_usd=float(fm.get("cost_usd", 0.0)),
    )


def parse_lap(text: str, path: Path | None = None):  # noqa: ANN201 — local import
    from autopilot.domain.experiment import Lap

    fm, body = _split_frontmatter(text, path)
    _check_keys(fm, _LAP_KEYS, path)
    lap_id = _require(fm, "id", path)
    experiment_id = _require(fm, "experiment_id", path)
    _require(fm, "verdict", path)
    fp = path if path is not None else Path("<memory>")
    if not body.strip():
        raise ParseError(file_path=fp, line_number=None, reason="lap body (spec) is required")
    signals_raw = fm.get("signals") or {}
    if not isinstance(signals_raw, dict):
        raise ParseError(file_path=fp, line_number=None, reason="signals: expected mapping")
    return Lap(
        id=str(lap_id),
        experiment_id=str(experiment_id),
        spec=body,
        branch=fm.get("branch"),
        signals=signals_raw,
        verdict=fm["verdict"],
        verdict_reason=fm.get("verdict_reason"),
        cost_usd=float(fm.get("cost_usd", 0.0)),
        started_at=_parse_dt_opt(fm.get("started_at"), path, "started_at"),
        completed_at=_parse_dt_opt(fm.get("completed_at"), path, "completed_at"),
    )


def parse_runner_output(text: str) -> tuple[str, dict[str, Any]]:
    """Parse frink-runner output: `### SPEC` prose + `### SIGNALS` yaml block.

    Returns (spec, signals). Raises ParseError when either section is missing
    or the signals yaml is not a mapping.
    """
    fp = Path("<memory>")
    spec_m = re.search(r"^###\s+SPEC\s*$", text, re.MULTILINE)
    signals_m = re.search(r"^###\s+SIGNALS\s*$", text, re.MULTILINE)
    if not spec_m:
        raise ParseError(file_path=fp, line_number=None, reason="runner output: missing ### SPEC")
    if not signals_m:
        raise ParseError(
            file_path=fp, line_number=None, reason="runner output: missing ### SIGNALS"
        )
    if signals_m.start() < spec_m.start():
        raise ParseError(
            file_path=fp, line_number=None, reason="runner output: SIGNALS precedes SPEC"
        )
    spec = text[spec_m.end() : signals_m.start()].strip()
    if not spec:
        raise ParseError(file_path=fp, line_number=None, reason="runner output: empty SPEC")
    signals_text = text[signals_m.end() :].strip()
    # Tolerate a ```yaml fence around the signals block.
    fence = re.match(r"^```(?:yaml)?\s*\n(.*?)\n?```\s*$", signals_text, re.DOTALL)
    if fence:
        signals_text = fence.group(1)
    try:
        signals = yaml.safe_load(signals_text) or {}
    except yaml.YAMLError as e:
        raise ParseError(
            file_path=fp, line_number=None, reason=f"runner output: signals yaml error: {e}"
        ) from e
    if not isinstance(signals, dict):
        raise ParseError(
            file_path=fp, line_number=None, reason="runner output: signals must be a mapping"
        )
    return spec, signals


@dataclass
class StopJudgeVerdict:
    verdict: str  # "merge" | "discard" | "iterate"
    reason: str
    done: bool


def parse_stop_judge_verdict(text: str) -> StopJudgeVerdict:
    """Parse `VERDICT: merge|discard|iterate`, `REASON: ...`, optional `DONE: yes|no`.

    Missing DONE defaults to no (keep iterating) per phase-5-frink.md §16.
    """
    fp = Path("<memory>")
    verdict_m = re.search(r"^VERDICT:\s*(\S+)\s*$", text, re.MULTILINE)
    if not verdict_m:
        raise ParseError(file_path=fp, line_number=None, reason="stop-judge: missing VERDICT:")
    verdict = verdict_m.group(1).strip().lower()
    if verdict not in ("merge", "discard", "iterate"):
        raise ParseError(
            file_path=fp, line_number=None, reason=f"stop-judge: unknown verdict {verdict!r}"
        )
    reason_m = re.search(
        r"^REASON:\s*(.*?)(?=^(?:DONE|VERDICT):|\Z)", text, re.MULTILINE | re.DOTALL
    )
    reason = reason_m.group(1).strip() if reason_m else ""
    if not reason:
        raise ParseError(file_path=fp, line_number=None, reason="stop-judge: missing REASON:")
    done_m = re.search(r"^DONE:\s*(\S+)\s*$", text, re.MULTILINE)
    done = bool(done_m and done_m.group(1).strip().lower() in ("yes", "true"))
    return StopJudgeVerdict(verdict=verdict, reason=reason, done=done)
