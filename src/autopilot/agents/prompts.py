"""Prompt builders per design §8. Accept entities, not dicts."""

from __future__ import annotations

import yaml

from autopilot.domain.goal import Goal
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import Sprint
from autopilot.domain.task import AttemptRecord, Task

# Task scope integrity — verbatim from `.dev/vision.md §Task Scope Integrity`.
# This is prompt-level protection (permission-level backstop is a follow-up).
_TASK_SCOPE_INTEGRITY = """\
## Task Scope Integrity

- The task file defines the work — you are executing against it, not authoring it.
- Done means done per the stated criterion — producing more than the DoD asks
  violates it, it does not satisfy it faster.
- Write scope is the project source files; task files, sprint files, and the
  roadmap are off-limits. Anything under `.dev/` that represents domain state is
  orchestrator-owned. Your entire concern is the codebase being built.
"""


def _fence(label: str, content: str) -> str:
    """Framed block with start/end sentinels — easy for the model to attend to."""
    return f"--- {label} START ---\n{content}\n--- {label} END ---"


def build_worker_prompt(
    task: Task,
    sprint: Sprint,
    prior_attempts: list[AttemptRecord],
) -> str:
    """Worker prompt: task intent + sprint context + task scope integrity + prior errors.

    Per design §9: retry prompt format (multi-line with blank separator) is preserved
    from the archived implementation.
    """
    sections: list[str] = [
        "You are executing a single task from the current sprint.",
        "",
        f"Sprint: {sprint.id} (primary goal: {sprint.primary_goal})",
        f"Task: {task.id}",
        "",
        _fence("SPRINT CONTEXT", sprint.context),
        "",
        _fence("TASK INTENT", task.intent.strip()),
    ]

    if prior_attempts:
        errors = [a.error for a in prior_attempts if a.error]
        if errors:
            retry_block_parts: list[str] = []
            for i, err in enumerate(errors, start=1):
                retry_block_parts.append(
                    f"IMPORTANT — RETRY ATTEMPT {i + 1}:\n"
                    f"The previous attempt failed with this error:\n"
                    f"{err}\n\n"
                    f"Address this failure specifically before proceeding."
                )
            sections += ["", _fence("PREVIOUS ATTEMPT ERRORS", "\n\n".join(retry_block_parts))]

    sections += ["", _TASK_SCOPE_INTEGRITY]
    sections += [
        "",
        "When done, emit a one-line summary prefixed `SUMMARY:` that describes what",
        "you accomplished. The orchestrator reads this line to record the task summary.",
    ]
    return "\n".join(sections)


def _goal_yaml(goal: Goal) -> str:
    data = {
        "id": goal.id,
        "priority": goal.priority,
        "status": goal.status,
    }
    if goal.summary:
        data["summary"] = goal.summary
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _prior_sprint_summary(sprint: Sprint) -> str:
    line = f"- {sprint.id} [{sprint.status}] (goal={sprint.primary_goal})"
    if sprint.summary:
        line += f": {sprint.summary}"
    return line


def build_planner_prompt(
    roadmap: Roadmap,
    goal: Goal,
    prior_sprints: list[Sprint],
    research: str | None,
    feedback: str | None = None,
) -> str:
    """Planner prompt: roadmap narrative + goal + prior sprints + research + feedback.

    Semantic intent matches the archived `build_planner_prompt`, re-expressed against
    the new entity shapes. Agent outputs are parsed into Sprint/Task entities downstream.
    """
    sections: list[str] = [
        "Plan the next sprint. Write a sprint context body and one markdown task file",
        "per task, each with full YAML frontmatter. The orchestrator will parse your",
        "output into Sprint and Task entities, so frontmatter must validate.",
        "",
        f"Archetype: {roadmap.archetype}",
        "",
        _fence("ROADMAP NARRATIVE", roadmap.narrative.strip()),
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
    ]

    if prior_sprints:
        summary_lines = [_prior_sprint_summary(s) for s in prior_sprints]
        sections += ["", _fence("PRIOR SPRINTS", "\n".join(summary_lines))]

    if research:
        sections += ["", _fence("RESEARCH", research.strip())]

    if feedback:
        sections += [
            "",
            "REVISION REQUIRED — The previous plan was reviewed and found not ready.",
            "Fix the issues below and rewrite the sprint plan.",
            "",
            _fence("FEEDBACK", feedback.strip()),
        ]

    sections += [
        "",
        "CONSTRAINT: Each sprint must leave the project in a working state",
        "(tests pass, no broken imports).",
    ]
    return "\n".join(sections)


def _sprint_yaml(sprint: Sprint) -> str:
    data = {
        "id": sprint.id,
        "primary_goal": sprint.primary_goal,
        "status": sprint.status,
    }
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _task_index(task: Task) -> str:
    deps = f" depends_on={task.depends_on}" if task.depends_on else ""
    return f"- {task.id} [{task.status}]{deps}: {task.intent.strip().splitlines()[0][:120]}"


def build_critic_prompt(sprint: Sprint, goal: Goal) -> str:
    """Critic prompt: review a sprint draft against the target goal."""
    task_lines = [_task_index(t) for t in sprint.tasks]
    sections = [
        "Review this sprint draft against its target goal. Your job is to identify",
        "what the plan missed — gaps, ambiguities, missing DoD, ordering issues,",
        "unstated assumptions — and return actionable critique.",
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT DRAFT", f"{_sprint_yaml(sprint)}\n\n{sprint.context.strip()}"),
        "",
        _fence("TASK LIST", "\n".join(task_lines) if task_lines else "(no tasks)"),
        "",
        "Be specific. Vague concerns ('needs more detail') do not improve the plan.",
    ]
    return "\n".join(sections)


def build_judge_prompt(sprint: Sprint, goal: Goal, critic_notes: str) -> str:
    """Judge prompt: approve or reject a sprint given critic notes."""
    task_lines = [_task_index(t) for t in sprint.tasks]
    sections = [
        "Judge whether this sprint is ready for autonomous execution against its goal.",
        "Read the sprint draft, the target goal, and the critic's notes, then decide.",
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT DRAFT", f"{_sprint_yaml(sprint)}\n\n{sprint.context.strip()}"),
        "",
        _fence("TASK LIST", "\n".join(task_lines) if task_lines else "(no tasks)"),
        "",
        _fence("CRITIC NOTES", critic_notes.strip() or "(no critic notes)"),
        "",
        "Respond with EXACTLY one of:",
        "",
        "VERDICT: READY",
        "(or)",
        "VERDICT: NOT_READY",
        "",
        "Followed by feedback explaining the decision. If NOT_READY, list the",
        "specific changes required before the sprint can be approved.",
    ]
    return "\n".join(sections)


def build_evaluator_prompt(sprint: Sprint, goal: Goal, roadmap: Roadmap) -> str:
    """Evaluator prompt: decide whether the goal is achieved after a sprint."""
    task_lines = [_task_index(t) for t in sprint.tasks]
    sections = [
        "Assess whether the target goal has been achieved given the sprint just",
        "completed and the overall roadmap context.",
        "",
        f"Archetype: {roadmap.archetype}",
        "",
        _fence("ROADMAP NARRATIVE", roadmap.narrative.strip()),
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT OUTCOME", f"{_sprint_yaml(sprint)}\n\n{sprint.context.strip()}"),
        "",
        _fence("TASK LIST", "\n".join(task_lines) if task_lines else "(no tasks)"),
    ]
    if sprint.summary:
        sections += ["", _fence("SPRINT SUMMARY", sprint.summary.strip())]

    sections += [
        "",
        "Respond with EXACTLY one of:",
        "",
        "GOAL_MET: YES",
        "(or)",
        "GOAL_MET: NO",
        "",
        "Followed by a concise assessment (2-5 sentences). If not satisfied,",
        "describe what remains.",
    ]
    return "\n".join(sections)
