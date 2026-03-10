"""Prompt builders for judge, worker, researcher, portfolio, and planner agents."""

import re
import textwrap
from pathlib import Path

from .manifest import MANIFEST_PATH
from .models import Manifest, Task


def build_judge_prompt(manifest: Manifest) -> str:
    """Build the prompt for the judge agent."""
    return textwrap.dedent(f"""\
        Evaluate the project manifest at `{MANIFEST_PATH}` in this directory.

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


def build_worker_prompt(manifest: Manifest, task: Task) -> str:
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

    return textwrap.dedent(f"""\
        You are working on the project in this directory.

        Read the project manifest at `{MANIFEST_PATH}` to understand the full
        project context, plan, and current progress.

        YOUR CURRENT TASK (task {task_index + 1} of {total}):
        "{task.title}"{task_detail}
        {retry_context}
        INSTRUCTIONS:
        1. Read relevant project files to understand the current state
        2. Implement the changes needed for this specific task
        3. Run any appropriate tests or checks to verify your work
        4. Commit your changes with a clear, descriptive commit message
        5. Mark this task as complete in `{MANIFEST_PATH}` by changing
           its checkbox from `### [ ]` to `### [x]`
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


def build_planner_prompt(project_path: Path, context_file: Path | None = None) -> str:
    """Build the prompt for the planner agent."""
    lines = [
        f"Analyze the project at `{project_path}` and create or improve the",
        f"task plan in `{MANIFEST_PATH}`.",
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


def build_critic_prompt(project_path: Path, context_file: Path | None = None) -> str:
    """Build the prompt for the critic agent."""
    lines = [
        f"Review the task plan at `.dev/autopilot.md` for the project at `{project_path}`.",
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
            "Use this to understand what the plan was trying to achieve when checking for blind spots.",
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
