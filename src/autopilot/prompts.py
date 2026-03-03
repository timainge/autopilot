"""Prompt builders for judge and worker agents."""

import re
import textwrap

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
    task_index = next(
        (i for i, t in enumerate(manifest.tasks) if t.id == task.id), 0
    )
    total = len(manifest.tasks)

    retry_context = ""
    if task.attempts > 0 and task.last_error:
        retry_context = textwrap.dedent(f"""\

            IMPORTANT — RETRY ATTEMPT {task.attempts + 1}:
            The previous attempt failed with this error:
            {task.last_error}

            Address this failure specifically before proceeding.
        """)

    return textwrap.dedent(f"""\
        You are working on the project in this directory.

        Read the project manifest at `{MANIFEST_PATH}` to understand the full
        project context, plan, and current progress.

        YOUR CURRENT TASK (task {task_index + 1} of {total}):
        "{task.title}"
        {retry_context}
        INSTRUCTIONS:
        1. Read relevant project files to understand the current state
        2. Implement the changes needed for this specific task
        3. Run any appropriate tests or checks to verify your work
        4. Commit your changes with a clear, descriptive commit message
        5. Mark this task as complete in `{MANIFEST_PATH}` by changing
           its checkbox from `- [ ]` to `- [x]`
        6. Provide a brief summary of what you accomplished

        RULES:
        - Stay focused on THIS task only — do not work on other tasks
        - If you encounter a blocking issue, describe it clearly and stop
        - Make atomic, well-tested commits
        - Do not modify other tasks' checkboxes
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
