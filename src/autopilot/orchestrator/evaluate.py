"""Sprint-level evaluator. Per design §7.3, workflows §5.3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autopilot.agents.prompts import build_evaluator_prompt
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.errors import SprintEvaluatorError
from autopilot.domain.eval import EvalContext, run_eval
from autopilot.domain.goal import Goal
from autopilot.domain.ids import EvalRef
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import Sprint
from autopilot.domain.task import Task


@dataclass
class EvaluatorVerdict:
    achieved: bool
    summary: str
    reasoning: str
    # Prose remediation guidance for the next planner when achieved=False.
    # None when achieved=True. Sourced from evaluator output minus the marker
    # and SUMMARY: lines, capped to cfg.verdict_reasoning_max_chars.
    feedback: str | None = None


def _entity_dir_for(entity: Any) -> Path:
    """Best-effort directory of the entity's persisted file."""
    if isinstance(entity, Sprint):
        if entity._dir is None:
            raise ValueError("sprint missing _dir")
        return entity._dir
    if isinstance(entity, Task):
        if entity._path is None:
            raise ValueError("task missing _path")
        return entity._path.parent
    if isinstance(entity, Goal):
        if entity._path is None:
            raise ValueError("goal missing _path")
        return entity._path.parent
    if isinstance(entity, Roadmap):
        if entity._path is None:
            raise ValueError("roadmap missing _path")
        return entity._path.parent
    raise TypeError(f"unsupported entity for build_eval_context: {type(entity).__name__}")


def build_eval_context(
    ref: EvalRef,
    entity: Any,
    *,
    project_root: Path,
    cfg: AutopilotConfig,
) -> EvalContext:
    """Assemble an EvalContext for running an eval against `entity`.

    Payload keys mirror workflows §3.8. Phase 1 intentionally omits git-diff
    collection for task payloads (TODO: wire once worktree semantics land).
    """
    payload: dict[str, Any] = {
        "project_root": project_root,
        "entity_dir": _entity_dir_for(entity),
        "worker_model": cfg.worker_model,
        "cfg": cfg,
    }
    match ref.entity_type:
        case "task":
            task = entity
            payload["task_intent"] = getattr(task, "intent", "")
            payload["task_summary"] = getattr(task, "summary", None)
            payload["prior_attempts"] = list(getattr(task, "attempts", []))
            # TODO(phase-2): include `git diff` against sprint start for task evals.
        case "sprint":
            sprint = entity
            payload["sprint_id"] = sprint.id
            payload["sprint_context"] = sprint.context
            payload["sprint_summary"] = sprint.summary
            payload["task_summaries"] = [
                {"id": t.id, "status": t.status, "summary": t.summary} for t in sprint.tasks
            ]
        case "goal":
            payload["goal_id"] = entity.id
            payload["goal_intent"] = entity.intent
            payload["goal_summary"] = entity.summary
        case "roadmap":
            payload["archetype"] = entity.archetype
            payload["roadmap_narrative"] = entity.narrative
    return EvalContext(entity=entity, payload=payload)


def _parse_evaluator_verdict(text: str) -> bool | None:
    """Return True/False if a GOAL_MET marker is present; None if absent."""
    for line in text.splitlines():
        stripped = line.strip().upper()
        if stripped.startswith("GOAL_MET: YES") or stripped.startswith("ACHIEVED: TRUE"):
            return True
        if stripped.startswith("GOAL_MET: NO") or stripped.startswith("ACHIEVED: FALSE"):
            return False
    return None


def _extract_feedback(text: str, max_chars: int) -> str | None:
    """Body of the evaluator output minus marker and SUMMARY: lines.

    Used as `EvaluatorVerdict.feedback` when achieved=False — surfaced to the
    next planner as remediation guidance.
    """
    keep: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().upper()
        if stripped.startswith(("GOAL_MET:", "ACHIEVED:", "SUMMARY:")):
            continue
        keep.append(line)
    body = "\n".join(keep).strip()
    if not body:
        return None
    return body[:max_chars]


async def sprint_evaluate(
    sprint: Sprint,
    goal: Goal,
    roadmap: Roadmap,
    cfg: AutopilotConfig,
    project: Path,
) -> EvaluatorVerdict:
    """Run goal mechanical evals first; fall through to evaluator agent.

    Mechanical evals are authoritative (workflows §7 row 21). The evaluator
    agent only runs when all mechanical evals pass (or none exist).
    """
    reasoning_chars = cfg.verdict_reasoning_max_chars
    summary_chars = cfg.verdict_summary_max_chars
    # Mechanical goal evals.
    for idx, eval_def in enumerate(goal.eval):
        ref = EvalRef(entity_type="goal", entity_id=goal.id, eval_index=idx)
        ctx = build_eval_context(ref, goal, project_root=project, cfg=cfg)
        run = await run_eval(eval_def, ref, ctx)
        if run.status in ("error", "failed"):
            output = (run.output or "")[:reasoning_chars]
            return EvaluatorVerdict(
                achieved=False,
                summary=f"goal eval {idx} {run.status}",
                reasoning=output,
                feedback=output or None,
            )

    # Evaluator agent.
    result = await run_agent(
        "evaluator",
        build_evaluator_prompt(sprint, goal, roadmap),
        cfg,
        cwd=project,
    )
    if not result.success:
        # Infrastructure failure — escalate, don't loop into another sprint.
        raise SprintEvaluatorError(
            sprint_id=sprint.id,
            reason=f"evaluator call failed: {result.error or 'unknown evaluator error'}",
        )

    parsed = _parse_evaluator_verdict(result.output)
    if parsed is None:
        # Mechanical evals (if any) already passed, but the evaluator emitted
        # no GOAL_MET/ACHIEVED marker — treat as infra-error rather than
        # silently defaulting either way.
        raise SprintEvaluatorError(
            sprint_id=sprint.id,
            reason="evaluator output missing GOAL_MET marker",
        )
    achieved = parsed

    summary = (result.summary or result.output[:summary_chars] or "goal assessed").strip()
    feedback = None if achieved else _extract_feedback(result.output, reasoning_chars)
    return EvaluatorVerdict(
        achieved=achieved,
        summary=summary,
        reasoning=result.output[:reasoning_chars],
        feedback=feedback,
    )
