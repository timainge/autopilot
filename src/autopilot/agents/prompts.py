"""Prompt builders per design §8. Accept entities, not dicts."""

from __future__ import annotations

from pathlib import Path

import yaml

from autopilot.domain.goal import Goal
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import Sprint
from autopilot.domain.task import AttemptRecord, Task

# How much task-intent text to include in prompt summary lines.
_INTENT_SNIPPET_CHARS = 120

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


_PLANNER_OUTPUT_CONTRACT = """\
OUTPUT CONTRACT — strict. The orchestrator parses your response text by
splitting on `### FILE:` headers. Do not write to disk; return one response
containing one sprint block and one block per task.

Format (exact):

    ### FILE: sprint-NNN.md
    ---
    id: sprint-NNN
    primary_goal: <goal-id>
    status: planning
    ---

    # Sprint NNN — <title>

    ## Context
    <prose>

    ## Tasks
    - [001](task-001.md): <summary>
    - [002](task-002.md): <summary>

    ### FILE: task-001.md
    ---
    id: '001'
    depends_on: []
    status: pending
    eval: []
    attempts: []
    summary: null
    ---

    # <task title>
    <prose + Done: + optional Watch:>

    ### FILE: task-002.md
    ...

Rules:
- Exactly one `sprint-NNN.md` block; the parser keys on that filename.
- One `task-NNN.md` block per task, filenames zero-padded three digits.
- Every frontmatter field above is required. Unknown fields are rejected.
- No prose or code fences outside the blocks. No leading preamble. The
  parser splits strictly on the `### FILE:` line."""


def build_planner_prompt(
    roadmap: Roadmap,
    goal: Goal,
    prior_sprints: list[Sprint],
    research: str | None,
    feedback: str | None = None,
) -> str:
    """Planner prompt: roadmap narrative + goal + prior sprints + research + feedback.

    Output is parsed into Sprint/Task entities by `_parse_planner_output` (plan.py):
    the prompt specifies the `### FILE:` envelope contract literally so the model
    cannot drift onto a side-writes-files interpretation.
    """
    sections: list[str] = [
        "Plan the next sprint against the target goal below.",
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
        "",
        _PLANNER_OUTPUT_CONTRACT,
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
    return (
        f"- {task.id} [{task.status}]{deps}: "
        f"{task.intent.strip().splitlines()[0][:_INTENT_SNIPPET_CHARS]}"
    )


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


_ROADMAP_OUTPUT_CONTRACT = """\
OUTPUT CONTRACT — strict. The orchestrator parses your response text by
splitting on `### FILE:` headers. Do not write to disk; return one response
containing one roadmap block and one block per goal.

Format (exact):

    ### FILE: roadmap.md
    ---
    archetype: <archetype-id>
    eval: []
    ---

    # Roadmap
    <narrative>

    ### FILE: goal-<id>.md
    ---
    id: <goal-id>
    priority: 1
    status: pending
    eval: []
    achieved_by: []
    summary: null
    ---

    # Goal: <title>
    <intent>

Rules:
- Exactly one `roadmap.md` block.
- One `goal-<id>.md` block per goal; ids slug-style.
- Priority ordering starts at 1 and increments.
- No prose outside the blocks."""


def build_researcher_prompt(topic: str, project_root: Path) -> str:
    """Researcher prompt: topic + project root. Output is raw markdown (no FILE: envelope)."""
    return (
        f"Research the topic `{topic}` for the project at `{project_root}`. "
        "Explore the codebase as needed, then return a concise markdown summary "
        "of your findings. Your entire response becomes the research document — "
        "no leading preamble, no file envelope.\n"
    )


def build_roadmap_prompt(
    project_root: Path,
    *,
    research: str | None = None,
    existing_roadmap: str | None = None,
) -> str:
    """Roadmap prompt: create or revise. Emits `### FILE:` envelopes parsed by the CLI."""
    sections: list[str] = []
    if existing_roadmap is not None:
        sections.append(
            "Revise the existing roadmap for this project. Update goals, add or "
            "remove them as needed, and rewrite the narrative."
        )
        sections += ["", _fence("EXISTING ROADMAP", existing_roadmap.strip())]
    else:
        sections.append(
            "Create a shipping roadmap for this project. Pick a concrete target, "
            "write the narrative, and enumerate initial goals."
        )
    sections += ["", f"Project root: {project_root}"]
    if research:
        sections += ["", _fence("RESEARCH", research.strip())]
    sections += ["", _ROADMAP_OUTPUT_CONTRACT]
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
