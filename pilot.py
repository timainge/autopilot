#!/usr/bin/env python3
"""
Session Pilot — Autonomous project session orchestrator.

Reads project manifests (.autopilot.md), evaluates readiness via an LLM judge,
and executes tasks sequentially through Claude Code via the Agent SDK.

Usage:
    python pilot.py /path/to/project
    python pilot.py /path/to/project1 /path/to/project2
    python pilot.py --scan ~/Projects
"""

import argparse
import asyncio
import re
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_DIR = ".dev"
MANIFEST_FILENAME = "autopilot.md"
MANIFEST_PATH = f"{MANIFEST_DIR}/{MANIFEST_FILENAME}"
AGENTS_DIR = Path(__file__).parent / "agents"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str
    title: str
    status: str  # pending, in-progress, done, failed, blocked, skipped
    depends: list[str] = field(default_factory=list)
    attempts: int = 0
    last_error: str | None = None
    line_number: int = 0  # line in manifest for rewriting


@dataclass
class Manifest:
    path: Path
    name: str
    approved: bool = False
    status: str = "pending"
    worktree: bool = False
    branch_prefix: str = "autopilot"
    max_budget_usd: float = 5.0
    max_task_attempts: int = 3
    tasks: list[Task] = field(default_factory=list)
    body: str = ""  # full markdown body (plan context for agents)
    raw: str = ""  # raw file content for rewriting


@dataclass
class AgentConfig:
    name: str
    description: str = ""
    system_prompt: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    max_turns: int | None = None
    max_budget_usd: float | None = None
    model: str | None = None


@dataclass
class AgentResult:
    success: bool
    output: str = ""
    error: str | None = None
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Logging / status output
# ---------------------------------------------------------------------------


def log(project: str, message: str, icon: str = "•") -> None:
    """Print timestamped status line."""
    ts = datetime.now().strftime("%H:%M:%S")
    name = project[:30]
    print(f"  [{ts}] [{name}] {icon} {message}")


def log_header(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n  [{ts}] {message}")
    print(f"  {'─' * 60}")


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    # Replace common separators with spaces before stripping
    text = re.sub(r"[/\\.:]+", " ", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split markdown into YAML frontmatter dict and body."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}

    body = parts[2].strip()
    return fm, body


def parse_tasks(content: str) -> list[Task]:
    """Parse markdown task checkboxes from content.

    Formats supported:
        - [ ] Task title
        - [x] Done task
        - [ ] Task with deps [depends: other-task, another-task]
        - [ ] Task with multiple metadata [id: custom-id] [depends: foo]

    Each metadata field should be in its own brackets.
    """
    tasks: list[Task] = []
    task_pattern = re.compile(
        r"^(\s*)-\s+\[([ xX])\]\s+(.+)$", re.MULTILINE
    )

    for i, match in enumerate(task_pattern.finditer(content)):
        checkbox = match.group(2).strip().lower()
        raw_title = match.group(3).strip()
        line_number = content[: match.start()].count("\n") + 1

        # Extract inline metadata [key: value]
        meta: dict[str, str] = {}
        title_clean = raw_title
        for meta_match in re.finditer(r"\[(\w+):\s*([^\]]+)\]", raw_title):
            meta[meta_match.group(1).lower()] = meta_match.group(2).strip()
            title_clean = title_clean.replace(meta_match.group(0), "").strip()

        task_id = meta.get("id", slugify(title_clean))
        depends_str = meta.get("depends", "")
        depends = [d.strip() for d in depends_str.split(",") if d.strip()] if depends_str else []

        status = "done" if checkbox == "x" else "pending"

        tasks.append(Task(
            id=task_id,
            title=title_clean,
            status=status,
            depends=depends,
            line_number=line_number,
        ))

    return tasks


def load_manifest(path: Path) -> Manifest | None:
    """Load and parse a project manifest file."""
    manifest_path = path / MANIFEST_DIR / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None

    content = manifest_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    tasks = parse_tasks(content)

    return Manifest(
        path=manifest_path,
        name=fm.get("name", path.name),
        approved=fm.get("approved", False),
        status=fm.get("status", "pending"),
        worktree=fm.get("worktree", False),
        branch_prefix=fm.get("branch_prefix", "autopilot"),
        max_budget_usd=fm.get("max_budget_usd", 5.0),
        max_task_attempts=fm.get("max_task_attempts", 3),
        tasks=tasks,
        body=body,
        raw=content,
    )


# ---------------------------------------------------------------------------
# Manifest writing
# ---------------------------------------------------------------------------


def update_task_status(manifest: Manifest, task_id: str, new_status: str,
                       error: str | None = None) -> None:
    """Update a task's status in the manifest file on disk.

    Rewrites the checkbox and appends attempt/error metadata inline.
    """
    content = manifest.path.read_text(encoding="utf-8")
    lines = content.split("\n")

    for task in manifest.tasks:
        if task.id != task_id:
            continue

        # Find the line with this task's checkbox
        # Search for the task title in checkbox lines
        for i, line in enumerate(lines):
            checkbox_match = re.match(r"^(\s*)-\s+\[([ xX])\]\s+(.+)$", line)
            if not checkbox_match:
                continue

            raw_title = checkbox_match.group(3).strip()
            # Remove metadata brackets to get clean title
            clean = re.sub(r"\[(\w+):\s*[^\]]+\]", "", raw_title).strip()
            line_id = slugify(clean)

            # Also check for explicit [id: ...] metadata
            id_match = re.search(r"\[id:\s*([^\]]+)\]", raw_title)
            if id_match:
                line_id = id_match.group(1).strip()

            if line_id != task_id:
                continue

            # Found our line — rewrite it
            indent = checkbox_match.group(1)
            if new_status == "done":
                mark = "x"
            else:
                mark = " "

            # Rebuild line: preserve existing metadata, update status-related ones
            # Remove old [status: ...] and [error: ...] tags
            title_part = re.sub(r"\s*\[status:\s*[^\]]+\]", "", raw_title)
            title_part = re.sub(r"\s*\[error:\s*[^\]]+\]", "", title_part)

            if new_status == "failed" and error:
                short_error = error[:120].replace("\n", " ").replace("]", ")")
                title_part += f" [status: failed] [error: {short_error}]"

            lines[i] = f"{indent}- [{mark}] {title_part}"

            # Update in-memory task too
            task.status = new_status
            if error:
                task.last_error = error
                task.attempts += 1
            break
        break

    new_content = "\n".join(lines)
    manifest.path.write_text(new_content, encoding="utf-8")
    manifest.raw = new_content


def update_manifest_frontmatter(manifest: Manifest, updates: dict[str, Any]) -> None:
    """Update frontmatter fields in the manifest file."""
    content = manifest.path.read_text(encoding="utf-8")

    if not content.startswith("---"):
        return

    parts = content.split("---", 2)
    if len(parts) < 3:
        return

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return

    fm.update(updates)
    new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{new_fm}---{parts[2]}"
    manifest.path.write_text(new_content, encoding="utf-8")

    # Update in-memory
    for key, value in updates.items():
        if hasattr(manifest, key):
            setattr(manifest, key, value)


# ---------------------------------------------------------------------------
# Agent config loading
# ---------------------------------------------------------------------------


def load_agent_config(name: str, agents_dir: Path | None = None) -> AgentConfig:
    """Load an agent role config from a markdown file with frontmatter."""
    search_dir = agents_dir or AGENTS_DIR
    agent_path = search_dir / f"{name}.md"

    if not agent_path.exists():
        raise FileNotFoundError(f"Agent config not found: {agent_path}")

    content = agent_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    return AgentConfig(
        name=fm.get("name", name),
        description=fm.get("description", ""),
        system_prompt=body.strip(),
        allowed_tools=fm.get("allowed_tools", ["Read", "Glob", "Bash"]),
        permission_mode=fm.get("permission_mode", "default"),
        max_turns=fm.get("max_turns"),
        max_budget_usd=fm.get("max_budget_usd"),
        model=fm.get("model"),
    )


# ---------------------------------------------------------------------------
# Task selection
# ---------------------------------------------------------------------------


def get_next_task(manifest: Manifest) -> Task | None:
    """Find the next pending task whose dependencies are all done."""
    done_ids = {t.id for t in manifest.tasks if t.status == "done"}

    for task in manifest.tasks:
        if task.status != "pending":
            continue
        if task.attempts >= manifest.max_task_attempts:
            continue
        if all(dep in done_ids for dep in task.depends):
            return task

    return None


def get_task_summary(manifest: Manifest) -> str:
    """Return a one-line summary of task progress."""
    total = len(manifest.tasks)
    done = sum(1 for t in manifest.tasks if t.status == "done")
    failed = sum(1 for t in manifest.tasks if t.status == "failed")
    pending = total - done - failed
    return f"{done}/{total} done, {pending} pending, {failed} failed"


# ---------------------------------------------------------------------------
# Agent execution via Claude Agent SDK
# ---------------------------------------------------------------------------


async def run_agent(
    agent_config: AgentConfig,
    cwd: Path,
    prompt: str,
) -> AgentResult:
    """Execute an agent session using the Claude Agent SDK's query()."""
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        return AgentResult(
            success=False,
            error="claude_agent_sdk not installed. Run: pip install claude-agent-sdk",
        )

    options = ClaudeAgentOptions(
        system_prompt=agent_config.system_prompt or None,
        allowed_tools=agent_config.allowed_tools,
        cwd=str(cwd),
    )

    if agent_config.permission_mode and agent_config.permission_mode != "default":
        options.permission_mode = agent_config.permission_mode

    if agent_config.max_turns:
        options.max_turns = agent_config.max_turns

    if agent_config.max_budget_usd:
        options.max_budget_usd = agent_config.max_budget_usd

    if agent_config.model:
        options.model = agent_config.model

    # Pick up project-level .claude/ config if present
    options.setting_sources = ["project"]

    output_parts: list[str] = []
    total_cost = 0.0

    try:
        async for message in query(prompt=prompt, options=options):
            # Extract text content from assistant messages
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        output_parts.append(block.text)

            # Extract cost from result messages
            if hasattr(message, "cost_usd"):
                total_cost = message.cost_usd or 0.0
            elif hasattr(message, "result"):
                # ResultMessage may have cost info
                if hasattr(message, "cost_usd"):
                    total_cost = message.cost_usd or 0.0

        return AgentResult(
            success=True,
            output="\n".join(output_parts),
            cost_usd=total_cost,
        )

    except Exception as e:
        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Judge: evaluate manifest readiness
# ---------------------------------------------------------------------------


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


def parse_judge_result(output: str) -> tuple[bool, str]:
    """Parse the judge agent's verdict and feedback."""
    is_ready = "VERDICT: READY" in output and "VERDICT: NOT_READY" not in output

    # Extract feedback section
    feedback = output
    feedback_match = re.search(r"FEEDBACK:\s*(.+?)(?=SUGGESTIONS:|$)", output, re.DOTALL)
    if feedback_match:
        feedback = feedback_match.group(1).strip()

    suggestions_match = re.search(r"SUGGESTIONS:\s*(.+?)$", output, re.DOTALL)
    if suggestions_match:
        feedback += "\n\nSuggestions:\n" + suggestions_match.group(1).strip()

    return is_ready, feedback


# ---------------------------------------------------------------------------
# Worker: execute a task
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Orchestration loop
# ---------------------------------------------------------------------------


async def process_project(project_path: Path, agents_dir: Path | None = None) -> None:
    """Process a single project through the orchestration pipeline."""
    project_name = project_path.name

    # Load manifest
    manifest = load_manifest(project_path)
    if manifest is None:
        log(project_name, f"No {MANIFEST_PATH} found — skipping", "⏭️")
        return

    log(project_name, f"Loaded manifest: {manifest.name} ({get_task_summary(manifest)})", "📋")

    # Skip completed projects
    if manifest.status == "completed":
        log(project_name, "Project already completed", "✅")
        return

    if manifest.status == "paused":
        log(project_name, "Project is paused — skipping", "⏸️")
        return

    # --- Step 1: Check approval / run judge ---

    if not manifest.approved:
        log(project_name, "Not approved — running readiness evaluation...", "🔍")

        try:
            judge_config = load_agent_config("judge", agents_dir)
        except FileNotFoundError:
            log(project_name, "No judge agent config found — skipping", "❌")
            return

        judge_prompt = build_judge_prompt(manifest)
        result = await run_agent(judge_config, project_path, judge_prompt)

        if not result.success:
            log(project_name, f"Judge failed: {result.error}", "❌")
            return

        is_ready, feedback = parse_judge_result(result.output)

        if is_ready:
            log(project_name, "Judge verdict: READY", "✅")
            log(project_name, "Set 'approved: true' in manifest to begin execution", "👉")
        else:
            log(project_name, "Judge verdict: NOT READY", "⚠️")

        # Print feedback indented
        for line in feedback.split("\n")[:15]:  # cap output
            if line.strip():
                print(f"           {line}")

        if result.cost_usd > 0:
            log(project_name, f"Judge cost: ${result.cost_usd:.4f}", "💰")

        return  # Never auto-approve — human must set approved: true

    # --- Step 2: Execute tasks sequentially ---

    update_manifest_frontmatter(manifest, {"status": "active"})

    while True:
        task = get_next_task(manifest)

        if task is None:
            # Check if all tasks are done
            all_done = all(t.status == "done" for t in manifest.tasks)
            if all_done:
                update_manifest_frontmatter(manifest, {"status": "completed"})
                log(project_name, f"All tasks complete! ({get_task_summary(manifest)})", "🎉")
            else:
                stuck_tasks = [
                    t for t in manifest.tasks
                    if t.status != "done" and t.attempts >= manifest.max_task_attempts
                ]
                blocked_tasks = [
                    t for t in manifest.tasks
                    if t.status == "pending" and not all(
                        dep in {tt.id for tt in manifest.tasks if tt.status == "done"}
                        for dep in t.depends
                    )
                ]
                if stuck_tasks:
                    log(project_name, f"Stuck — {len(stuck_tasks)} task(s) exceeded max attempts", "🛑")
                    for t in stuck_tasks:
                        log(project_name, f"  → {t.title} ({t.attempts} attempts)", "")
                elif blocked_tasks:
                    log(project_name, f"Blocked — {len(blocked_tasks)} task(s) have unsatisfied deps", "🛑")
                else:
                    log(project_name, f"No runnable tasks remain ({get_task_summary(manifest)})", "🛑")

                update_manifest_frontmatter(manifest, {"status": "paused"})
            break

        task_idx = next(
            (i for i, t in enumerate(manifest.tasks) if t.id == task.id), 0
        )
        total = len(manifest.tasks)
        attempt_str = f" (attempt {task.attempts + 1})" if task.attempts > 0 else ""

        log(project_name,
            f"Starting task {task_idx + 1}/{total}: \"{task.title}\"{attempt_str}",
            "🔧")

        # Load worker config
        try:
            worker_config = load_agent_config("worker", agents_dir)
        except FileNotFoundError:
            log(project_name, "No worker agent config found — stopping", "❌")
            break

        # Execute
        worker_prompt = build_worker_prompt(manifest, task)
        result = await run_agent(worker_config, project_path, worker_prompt)

        if result.cost_usd > 0:
            log(project_name, f"Task cost: ${result.cost_usd:.4f}", "💰")

        # Check outcome
        if result.success:
            # Reload manifest to see if worker marked the task done
            updated_manifest = load_manifest(project_path)
            if updated_manifest:
                updated_task = next(
                    (t for t in updated_manifest.tasks if t.id == task.id), None
                )
                if updated_task and updated_task.status == "done":
                    log(project_name, f"Task complete: \"{task.title}\"", "✅")
                    # Refresh our in-memory manifest
                    manifest = updated_manifest
                    continue
                else:
                    # Worker succeeded but didn't mark task done — treat as failure
                    log(project_name,
                        f"Worker finished but task not marked done — treating as incomplete",
                        "⚠️")
                    task.attempts += 1
                    update_task_status(manifest, task.id, "pending",
                                      "Worker completed without marking task done")
                    manifest = load_manifest(project_path) or manifest
            else:
                log(project_name, "Could not reload manifest after task", "❌")
                break
        else:
            error_msg = result.error or "Unknown error"
            log(project_name, f"Task failed: {error_msg[:100]}", "❌")

            task.attempts += 1
            if task.attempts >= manifest.max_task_attempts:
                update_task_status(manifest, task.id, "failed", error_msg)
                log(project_name,
                    f"Task \"{task.title}\" exceeded {manifest.max_task_attempts} attempts — marking failed",
                    "🛑")
            else:
                update_task_status(manifest, task.id, "pending", error_msg)
                log(project_name,
                    f"Will retry ({task.attempts}/{manifest.max_task_attempts})",
                    "🔄")

            manifest = load_manifest(project_path) or manifest


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


def discover_projects(scan_dir: Path) -> list[Path]:
    """Find all directories containing a manifest under scan_dir."""
    projects = []
    for child in sorted(scan_dir.iterdir()):
        if child.is_dir() and (child / MANIFEST_DIR / MANIFEST_FILENAME).exists():
            projects.append(child)
    return projects


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Session Pilot — autonomous project session orchestrator",
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project directories to process",
    )
    parser.add_argument(
        "--scan",
        type=Path,
        help="Scan a directory for projects containing .autopilot.md",
    )
    parser.add_argument(
        "--agents-dir",
        type=Path,
        default=None,
        help="Directory containing agent role configs (default: ./agents/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing agents",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # Resolve agent config directory
    agents_dir = args.agents_dir or AGENTS_DIR

    # Collect project paths
    project_paths: list[Path] = []

    if args.scan:
        project_paths = discover_projects(args.scan.expanduser().resolve())
        if not project_paths:
            print(f"  No projects with {MANIFEST_PATH} found under {args.scan}")
            sys.exit(0)
    elif args.projects:
        project_paths = [Path(p).expanduser().resolve() for p in args.projects]
    else:
        # Default: check current directory
        cwd = Path.cwd()
        if (cwd / MANIFEST_DIR / MANIFEST_FILENAME).exists():
            project_paths = [cwd]
        else:
            print(f"  No {MANIFEST_PATH} in current directory. Provide paths or use --scan.")
            sys.exit(1)

    # Header
    log_header(f"Session Pilot — {len(project_paths)} project(s)")

    if args.dry_run:
        print("  [DRY RUN MODE — no agents will be executed]\n")
        for path in project_paths:
            manifest = load_manifest(path)
            if manifest:
                status = "✅ approved" if manifest.approved else "⏳ needs review"
                print(f"  {path.name}: {manifest.name} — {status} — {get_task_summary(manifest)}")
            else:
                print(f"  {path.name}: no manifest")
        return

    # Process each project
    for project_path in project_paths:
        if not project_path.is_dir():
            log(str(project_path), "Not a directory — skipping", "⏭️")
            continue
        await process_project(project_path, agents_dir)

    # Footer
    log_header("Session Pilot — complete")


if __name__ == "__main__":
    asyncio.run(main())
