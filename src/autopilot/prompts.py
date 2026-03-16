"""Prompt builders for judge, worker, researcher, portfolio, and planner agents."""

import re
import textwrap
from pathlib import Path

from .manifest import SPRINT_PATH
from .models import Manifest, Task


def build_judge_prompt(manifest: Manifest, sprint_plan_path: str | None = None) -> str:
    """Build the prompt for the judge agent."""
    plan_path = sprint_plan_path if sprint_plan_path is not None else SPRINT_PATH
    return textwrap.dedent(f"""\
        Evaluate the project manifest at `{plan_path}` in this directory.

        Determine whether this project is ready for autonomous task execution.

        Check the following:
        1. Does the manifest have a clear project description?
        2. Are the tasks well-defined and actionable by a coding agent?
        3. Are task dependencies logical (no circular deps, correct ordering)?
        4. Is there enough context for a worker agent to execute each task
           without human clarification?
        5. Does the project have the basics in place (e.g., package.json,
           pyproject.toml, or equivalent for the tech stack)?

        Respond with EXACTLY this format:

        VERDICT: READY
        (or)
        VERDICT: NOT_READY

        FEEDBACK:
        <your detailed assessment — what's good, what needs work>

        SUGGESTIONS:
        <if NOT_READY, specific actions to make it ready>
    """)


def build_worker_prompt(
    manifest: Manifest,
    task: Task,
    sprint_plan_path: str | None = None,
) -> str:
    """Build the prompt for a worker agent executing a specific task."""
    task_index = next((i for i, t in enumerate(manifest.tasks) if t.id == task.id), 0)
    total = len(manifest.tasks)

    retry_context = ""
    if task.attempts > 0 and task.last_error:
        retry_context = textwrap.dedent(f"""\

            IMPORTANT — RETRY ATTEMPT {task.attempts + 1}:
            The previous attempt failed with this error:
            {task.last_error}

            Address this failure specifically before proceeding.
        """)

    task_detail = f"\n\n{task.body.strip()}" if task.body and task.body.strip() else ""

    if sprint_plan_path is not None:
        manifest_instruction = (
            f"Read the sprint plan at `{sprint_plan_path}` to understand the current sprint's"
            f" tasks.\n"
            f"        Also read `.dev/roadmap.md` for overall goal context."
        )
        mark_done_instruction = (
            f"5. Mark this task as complete in `{sprint_plan_path}` by changing\n"
            f"           its checkbox from `### [ ]` to `### [x]`"
        )
    else:
        manifest_instruction = (
            f"Read the sprint plan at `{SPRINT_PATH}` to understand the full\n"
            f"        project context, plan, and current progress."
        )
        mark_done_instruction = (
            f"5. Mark this task as complete in `{SPRINT_PATH}` by changing\n"
            f"           its checkbox from `### [ ]` to `### [x]`"
        )

    return textwrap.dedent(f"""\
        You are working on the project in this directory.

        {manifest_instruction}

        YOUR CURRENT TASK (task {task_index + 1} of {total}):
        "{task.title}"{task_detail}
        {retry_context}
        INSTRUCTIONS:
        1. Read relevant project files to understand the current state
        2. Implement the changes needed for this specific task
        3. Run any appropriate tests or checks to verify your work
        4. Commit your changes with a clear, descriptive commit message
        {mark_done_instruction}
        6. Provide a brief summary of what you accomplished

        RULES:
        - Stay focused on THIS task only — do not work on other tasks
        - If you encounter a blocking issue, describe it clearly and stop
        - Make atomic, well-tested commits
        - Do not modify other tasks' checkboxes
    """)


def build_researcher_prompt(project_path: Path) -> str:
    """Build the prompt for the researcher agent."""
    return textwrap.dedent(f"""\
        Analyze the project at `{project_path}`.

        Explore the codebase, git history, dependencies, and documentation to
        understand what this project is, its current state, and its potential.

        Write your findings to `.dev/project-summary.md` following the format
        described in your system prompt. Create the `.dev/` directory if it
        doesn't exist.
    """)


def build_portfolio_prompt(scan_dir: Path, project_paths: list[Path]) -> str:
    """Build the prompt for the portfolio agent."""
    with_summary = []
    without_summary = []
    for p in project_paths:
        if (p / ".dev" / "project-summary.md").exists():
            with_summary.append(p.name)
        else:
            without_summary.append(p.name)

    lines = [
        f"Analyze the projects under `{scan_dir}` and build a portfolio overview.",
        f"Write the output to `{scan_dir}/.dev/portfolio.md`.",
        "",
        f"Total projects: {len(project_paths)}",
        "",
    ]

    if with_summary:
        lines.append(f"Projects WITH research summaries ({len(with_summary)}):")
        for name in with_summary:
            lines.append(f"  - {name} (read {name}/.dev/project-summary.md)")
        lines.append("")

    if without_summary:
        lines.append(
            f"Projects WITHOUT summaries ({len(without_summary)}) — do a quick assessment:"
        )
        for name in without_summary:
            lines.append(f"  - {name}")
        lines.append("")

    return "\n".join(lines)


def build_planner_prompt(
    project_path: Path,
    context_file: Path | None = None,
    roadmap: str = "",
    runbook: str = "",
    sprint_log: str = "",
    sprint_mode: bool = False,
) -> str:
    """Build the prompt for the planner agent."""
    if sprint_mode:
        lines = [
            f"Analyze the project at `{project_path}` and write the next sprint's task plan",
            "to `.dev/sprint.md`.",
            "",
            "The sprint plan format is identical to the standard task format: use the same",
            "YAML frontmatter (approved, status, etc.) and markdown checkbox task list.",
            "",
            "CONSTRAINT: Each sprint must leave the project in a working state",
            "(tests pass, no broken imports).",
        ]

        if roadmap:
            lines += [
                "",
                "--- ROADMAP START ---",
                roadmap,
                "--- ROADMAP END ---",
            ]

        if runbook:
            lines += [
                "",
                "--- RUNBOOK START ---",
                runbook,
                "--- RUNBOOK END ---",
            ]

        if sprint_log:
            lines += [
                "",
                "--- SPRINT LOG START ---",
                sprint_log,
                "--- SPRINT LOG END ---",
            ]

        return "\n".join(lines)

    lines = [
        f"Analyze the project at `{project_path}` and create or improve the",
        "task plan in `.dev/sprint.md`.",
        "",
        "If no manifest exists yet, create one with appropriate frontmatter",
        "and a task list. If one exists, improve it.",
    ]

    if context_file:
        try:
            content = context_file.read_text(encoding="utf-8")
        except OSError:
            content = f"(could not read {context_file})"

        lines += [
            "",
            "Use the following file as additional context for planning.",
            f"Source: `{context_file}`",
            "",
            "--- CONTEXT START ---",
            content,
            "--- CONTEXT END ---",
            "",
            "After reading the above, complete Phase 1 exploration"
            " (read all referenced source files) before writing any tasks.",
        ]
    else:
        lines += [
            "",
            "No spec file was provided. Base Phase 1 exploration on the goal"
            " in the manifest frontmatter and your analysis of the codebase.",
        ]

    return "\n".join(lines)


def build_critic_prompt(
    project_path: Path,
    context_file: Path | None = None,
    sprint_mode: bool = False,
) -> str:
    """Build the prompt for the critic agent."""
    if sprint_mode:
        lines = [
            f"Review the sprint task plan at `.dev/sprint.md` for the project at `{project_path}`.",
            "",
            "The plan was written by a planner agent. Your job is to find what it missed",
            "and fix it directly in the sprint manifest. Follow the process in your system prompt.",
            "",
            "Note: the overall goal context lives in `.dev/roadmap.md` — read it to",
            "understand the goals this sprint should be advancing.",
        ]
        return "\n".join(lines)

    lines = [
        f"Review the task plan at `.dev/sprint.md` for the project at `{project_path}`.",
        "",
        "The plan was written by a planner agent. Your job is to find what it missed",
        "and fix it directly in the manifest. Follow the process in your system prompt.",
    ]

    if context_file:
        try:
            content = context_file.read_text(encoding="utf-8")
        except OSError:
            content = f"(could not read {context_file})"

        lines += [
            "",
            "The original planning context was:",
            f"Source: `{context_file}`",
            "",
            "--- CONTEXT START ---",
            content,
            "--- CONTEXT END ---",
            "",
            "Use this to understand what the plan was trying to achieve when checking for blind spots.",  # noqa: E501
        ]

    return "\n".join(lines)


def build_roadmap_prompt(project_path: Path) -> str:
    """Build the prompt for the roadmap agent."""
    has_summary = (project_path / ".dev" / "project-summary.md").exists()
    summary_hint = (
        "A research summary exists at `.dev/project-summary.md` — read it first."
        if has_summary
        else "No research summary exists — do a quick assessment of the project before planning."
    )
    return textwrap.dedent(f"""\
        Create a shipping roadmap for the project at `{project_path}`.

        {summary_hint}

        Write the roadmap to `.dev/roadmap.md` following the format in your system prompt.
    """)


def build_deep_researcher_prompt(
    project_path: Path,
    topic: str | None = None,
    topic_file: Path | None = None,
) -> str:
    """Build the prompt for the deep researcher agent."""
    if topic_file is not None:
        slug = re.sub(r"[^a-z0-9]+", "-", topic_file.stem[:40].lower()).strip("-")
        try:
            content = topic_file.read_text(encoding="utf-8")
        except OSError:
            content = f"(could not read {topic_file})"

        lines = [
            f"Research the following topic for the project at `{project_path}`.",
            "",
            f"Write your report to `.dev/research/{slug}/report.md`.",
            "",
            "The research brief is provided below.",
            f"Source: `{topic_file}`",
            "",
            "--- CONTEXT START ---",
            content,
            "--- CONTEXT END ---",
            "",
            "Parse the brief into 3-6 distinct lines of enquiry, research each thoroughly,"
            " then synthesize your findings into the report.",
        ]
        return "\n".join(lines)

    if topic is not None:
        slug = re.sub(r"[^a-z0-9]+", "-", topic[:40].lower()).strip("-")
        return textwrap.dedent(f"""\
            Research the following topic for the project at `{project_path}`.

            Topic: {topic}

            Write your report to `.dev/research/{slug}/report.md`.

            Parse the topic into 3-6 distinct lines of enquiry, research each thoroughly,
            then synthesize your findings into the report.
        """)

    # Project-analysis mode
    output_path = f".dev/research/{project_path.name}-project-analysis/report.md"
    return textwrap.dedent(f"""\
        Perform a comprehensive project analysis of `{project_path}`.

        Write your report to `{output_path}`.

        Explore the codebase thoroughly: architecture, key modules, test coverage
        (run the test suite if one exists), dependency health, and code quality
        (run the linter if present). Do web searches for comparable tools, recent
        activity in the space, and known issues with dependencies. Synthesize all
        findings into the structured report.
    """)


def build_evaluate_prompt(project_path: Path, sprint_log: str) -> str:
    """Build the prompt for the roadmap agent in evaluate mode."""
    return textwrap.dedent(f"""\
        Read the roadmap at `.dev/roadmap.md` for the project at `{project_path}`.

        Below is the sprint log summarising work completed so far:

        --- SPRINT LOG START ---
        {sprint_log}
        --- SPRINT LOG END ---

        Assess whether the goal and quality bar defined in the roadmap are satisfied
        based on the sprint log and current project state.

        Output EXACTLY one of:

        GOAL_MET: YES
        (or)
        GOAL_MET: NO

        Followed by a concise assessment (2-5 sentences). If not satisfied, describe what remains.
    """)


def parse_goal_result(output: str) -> tuple[bool, str]:
    """Parse the roadmap agent's evaluate verdict."""
    if "GOAL_MET: YES" in output:
        met = True
    elif "GOAL_MET: NO" in output:
        met = False
    else:
        return False, output
    assessment = re.sub(r"GOAL_MET:\s*(YES|NO)\s*", "", output, count=1).strip()
    return met, assessment


def parse_judge_result(output: str) -> tuple[bool, str]:
    """Parse the judge agent's verdict and feedback."""
    is_ready = "VERDICT: READY" in output and "VERDICT: NOT_READY" not in output

    feedback = output
    feedback_match = re.search(r"FEEDBACK:\s*(.+?)(?=SUGGESTIONS:|$)", output, re.DOTALL)
    if feedback_match:
        feedback = feedback_match.group(1).strip()

    suggestions_match = re.search(r"SUGGESTIONS:\s*(.+?)$", output, re.DOTALL)
    if suggestions_match:
        feedback += "\n\nSuggestions:\n" + suggestions_match.group(1).strip()

    return is_ready, feedback
