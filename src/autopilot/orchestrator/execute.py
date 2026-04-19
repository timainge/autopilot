"""Homer: sprint execution. Per design §7.1, workflows §5.2."""

from __future__ import annotations

from pathlib import Path

from autopilot.agents.prompts import build_worker_prompt
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.errors import EvalInfrastructureError
from autopilot.domain.eval import EvalContext, run_eval
from autopilot.domain.ids import EvalRef
from autopilot.domain.sprint import Sprint
from autopilot.domain.task import Task


def _latest_sprint_dir(project: Path) -> Path | None:
    sprints_dir = project / ".dev" / "sprints"
    if not sprints_dir.is_dir():
        return None
    candidates = sorted(
        [p for p in sprints_dir.glob("sprint-*") if p.is_dir()],
        key=lambda p: p.name,
    )
    return candidates[-1] if candidates else None


def deps_satisfied(task: Task, all_tasks: list[Task]) -> bool:
    by_id = {t.id: t for t in all_tasks}
    for dep in task.depends_on:
        dep_task = by_id.get(dep)
        if dep_task is None or dep_task.status != "completed":
            return False
    return True


def topo_sort(tasks: list[Task]) -> list[Task]:
    """Order tasks so dependencies come before dependents.

    Tasks with unknown deps (not in the list) are placed last but still yielded.
    Cycles cause any remaining tasks to be appended in input order.
    """
    remaining = list(tasks)
    ids = {t.id for t in remaining}
    out: list[Task] = []
    placed: set[str] = set()
    while remaining:
        progress = False
        for t in list(remaining):
            unmet = [d for d in t.depends_on if d in ids and d not in placed]
            if not unmet:
                out.append(t)
                placed.add(t.id)
                remaining.remove(t)
                progress = True
        if not progress:
            # cycle or external deps: fall through with input order
            out.extend(remaining)
            break
    return out


async def run_task(
    task: Task,
    sprint: Sprint,
    cfg: AutopilotConfig,
    project: Path,
) -> None:
    """Execute a task with retries. On all-retries-failed, task remains `failed`."""
    for _attempt in range(cfg.max_task_attempts):
        prior_attempts = list(task.attempts)
        task.start()

        result = await run_agent(
            "worker",
            build_worker_prompt(task, sprint, prior_attempts),
            cfg,
            cwd=project,
        )
        if not result.success:
            task.fail(result.error or "worker call failed")
            continue

        summary_chars = cfg.task_output_summary_chars
        eval_failed = False
        eval_error: str | None = None
        for idx, eval_def in enumerate(task.eval):
            ref = EvalRef(entity_type="task", entity_id=task.id, eval_index=idx)
            ctx = EvalContext(
                entity=task,
                payload={
                    "project_root": project,
                    "entity_dir": sprint._dir,
                    "worker_model": cfg.worker_model,
                    "cfg": cfg,
                },
            )
            run = await run_eval(eval_def, ref, ctx)
            if run.status == "error":
                task.fail(f"eval infrastructure error: {run.output[:summary_chars]}")
                raise EvalInfrastructureError(
                    eval_ref=f"task/{task.id}#{idx}",
                    reason=run.output[:summary_chars] or "unknown eval error",
                )
            if run.status == "failed":
                eval_failed = True
                eval_error = f"eval failed: {run.output[:summary_chars]}"
                break

        if eval_failed:
            task.fail(eval_error or "eval failed")
            continue

        summary = result.summary or (
            result.output[:summary_chars] if result.output else "task completed"
        )
        task.complete(summary=summary)
        return


async def homer(
    project: Path,
    cfg: AutopilotConfig,
    *,
    sprint_id: str | None = None,
) -> Sprint:
    """Execute the named sprint (or the latest). Returns the final Sprint state."""
    if sprint_id is not None:
        sprint_dir = project / ".dev" / "sprints" / sprint_id
    else:
        sprint_dir = _latest_sprint_dir(project)
        if sprint_dir is None:
            raise FileNotFoundError(f"no sprint dirs under {project / '.dev' / 'sprints'}")
    sprint = Sprint.load(sprint_dir)

    if sprint.status not in ("approved", "active"):
        raise ValueError(f"sprint {sprint.id} not runnable: status={sprint.status}")
    if sprint.status == "approved":
        sprint.start()

    # Resume recovery: a task left `active` from a killed prior run would raise
    # InvalidTransition on task.start(). Reset to `pending` so the run loop can
    # re-attempt it cleanly. The prior attempt record is preserved.
    for task in sprint.tasks:
        if task.status == "active":
            task.resume()

    ordered = topo_sort(sprint.tasks)

    try:
        while True:
            unfinished = [t for t in ordered if t.status not in ("completed", "failed")]
            if not unfinished:
                break
            progress = False
            for task in unfinished:
                if task.status == "completed":
                    continue
                if not deps_satisfied(task, sprint.tasks):
                    continue
                await run_task(task, sprint, cfg, project)
                progress = True
                if task.status == "failed":
                    # A failed task whose deps are satisfied counts as progress —
                    # we continue so dependents will be skipped-as-blocked next pass.
                    pass
            if not progress:
                sprint.fail("task dependency deadlock")
                return sprint
    except EvalInfrastructureError as e:
        sprint.fail(f"eval infrastructure error: {e}")
        return sprint

    if all(t.status == "completed" for t in sprint.tasks):
        completed_ids = [t.id for t in sprint.tasks]
        sprint.complete(summary=f"completed {len(completed_ids)} tasks: {completed_ids}")
    else:
        failed = [t.id for t in sprint.tasks if t.status == "failed"]
        sprint.fail(f"tasks failed: {failed}")
    return sprint
