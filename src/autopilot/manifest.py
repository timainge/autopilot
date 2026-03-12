"""Manifest parsing, loading, and writing."""

import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .models import AgentConfig, Manifest, Task

if TYPE_CHECKING:
    from .config import AutopilotConfig

MANIFEST_DIR = ".dev"
MANIFEST_FILENAME = "autopilot.md"
MANIFEST_PATH = f"{MANIFEST_DIR}/{MANIFEST_FILENAME}"


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
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
    """Parse header-based task sections from content.

    Tasks are defined as level-3 headings:
        ### [ ] task-id [depends: other-id]
        ### [x] task-id
    """
    tasks: list[Task] = []
    header_pattern = re.compile(r"^### \[([ xX])\] (.+)$", re.MULTILINE)

    matches = list(header_pattern.finditer(content))
    for idx, match in enumerate(matches):
        checkbox = match.group(1).strip().lower()
        raw_header = match.group(2).strip()
        line_number = content[: match.start()].count("\n") + 1

        # Extract [key: value] metadata from header
        meta: dict[str, str] = {}
        header_clean = raw_header
        for meta_match in re.finditer(r"\[(\w+):\s*([^\]]+)\]", raw_header):
            meta[meta_match.group(1).lower()] = meta_match.group(2).strip()
            header_clean = header_clean.replace(meta_match.group(0), "").strip()

        # The cleaned header text is the task ID (already slug-format from planner)
        task_id = header_clean.strip()
        # Fallback: slugify if the text isn't already slug-format
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", task_id):
            task_id = slugify(task_id)

        # Title: same as id for header-based format (no separate title field)
        title = header_clean.strip()

        depends_str = meta.get("depends", "")
        raw_deps = [d.strip() for d in depends_str.split(",") if d.strip()] if depends_str else []
        depends = [
            d if re.match(r"^[a-z0-9][a-z0-9-]*$", d) else slugify(d)
            for d in raw_deps
        ]
        attempts = int(meta.get("attempts", "0"))

        status = "done" if checkbox == "x" else "pending"
        if meta.get("status") == "failed":
            status = "failed"

        # Extract body: text between end of this header line and the next header or --- separator
        header_end = match.end()
        if idx + 1 < len(matches):
            next_start = matches[idx + 1].start()
            body_raw = content[header_end:next_start]
        else:
            body_raw = content[header_end:]

        # Trim trailing --- separator and surrounding whitespace
        body = re.sub(r"\s*---\s*$", "", body_raw.strip())
        body = body.strip()

        tasks.append(
            Task(
                id=task_id,
                title=title,
                status=status,
                depends=depends,
                attempts=attempts,
                body=body,
                line_number=line_number,
            )
        )

    return tasks


def load_manifest(path: Path, cfg: "AutopilotConfig | None" = None) -> Manifest | None:
    """Load and parse a project manifest file."""
    if cfg is not None:
        manifest_path = cfg.manifest_path(path)
    else:
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
        archetype=fm.get("archetype"),
        goal=fm.get("goal", "launch"),
        validate=fm.get("validate") or [],
        max_sprint_budget_usd=fm.get("max_sprint_budget_usd", 5.0),
        strategy=body,
    )


def update_task_status(
    manifest: Manifest,
    task_id: str,
    new_status: str,
    error: str | None = None,
    attempts: int | None = None,
) -> None:
    """Update a task's status in the manifest file on disk.

    Persists status, error, and attempt count as inline metadata so they
    survive manifest reloads.
    """
    content = manifest.path.read_text(encoding="utf-8")
    lines = content.split("\n")

    for task in manifest.tasks:
        if task.id != task_id:
            continue

        for i, line in enumerate(lines):
            header_match = re.match(r"^### \[([ xX])\] (.+)$", line)
            if not header_match:
                continue

            raw_header = header_match.group(2).strip()
            # Strip all [key: value] brackets to get the bare ID text
            bare = re.sub(r"\[(\w+):\s*[^\]]+\]", "", raw_header).strip()
            if not re.match(r"^[a-z0-9][a-z0-9-]*$", bare):
                bare = slugify(bare)

            if bare != task_id:
                continue

            mark = "x" if new_status == "done" else " "

            # Strip old status/error/attempts metadata from the header
            header_part = re.sub(r"\s*\[status:\s*[^\]]+\]", "", raw_header)
            header_part = re.sub(r"\s*\[error:\s*[^\]]+\]", "", header_part)
            header_part = re.sub(r"\s*\[attempts:\s*[^\]]+\]", "", header_part)

            # Append updated metadata
            if attempts is not None and attempts > 0:
                header_part += f" [attempts: {attempts}]"
            if new_status == "failed" and error:
                short_error = error[:120].replace("\n", " ").replace("]", ")")
                header_part += f" [status: failed] [error: {short_error}]"

            lines[i] = f"### [{mark}] {header_part}"

            # Update in-memory task
            task.status = new_status
            if error:
                task.last_error = error
            if attempts is not None:
                task.attempts = attempts
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

    for key, value in updates.items():
        if hasattr(manifest, key):
            setattr(manifest, key, value)


def load_agent_config(name: str, agents_dir: Path) -> AgentConfig:
    """Load an agent role config from a markdown file with frontmatter."""
    agent_path = agents_dir / f"{name}.md"

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


def reset_stuck_project(project_path: Path) -> bool:
    """Reset a stuck project so it can be resumed.

    Resets all failed tasks to pending with 0 attempts, and sets
    the project status from 'stuck' to 'active'.

    Returns True if the project was reset, False if it wasn't stuck.
    """
    manifest = load_manifest(project_path)
    if manifest is None or manifest.status != "stuck":
        return False

    failed_tasks = [t for t in manifest.tasks if t.status == "failed"]
    for task in failed_tasks:
        update_task_status(manifest, task.id, "pending", attempts=0)

    update_manifest_frontmatter(manifest, {"status": "active"})
    return True


def discover_projects(scan_dir: Path, cfg: "AutopilotConfig | None" = None) -> list[Path]:
    """Find all directories containing a manifest under scan_dir."""
    projects = []
    for child in sorted(scan_dir.iterdir()):
        if cfg is not None:
            manifest_exists = cfg.manifest_path(child).exists()
        else:
            manifest_exists = (child / MANIFEST_DIR / MANIFEST_FILENAME).exists()
        if child.is_dir() and manifest_exists:
            projects.append(child)
    return projects


# Markers that indicate a directory is a software project
_PROJECT_MARKERS = (
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "CMakeLists.txt",
    "build.gradle",
    "pom.xml",
    "Gemfile",
    "requirements.txt",
    "setup.py",
    "composer.json",
    "mix.exs",
)


def discover_all_projects(scan_dir: Path) -> list[Path]:
    """Find all project-like directories under scan_dir (for research mode)."""
    projects = []
    for child in sorted(scan_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if any((child / marker).exists() for marker in _PROJECT_MARKERS):
            projects.append(child)
    return projects


def _run_cmd(args: list[str], timeout: int = 5) -> str | None:
    """Run a command and return stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def detect_git_user() -> str | None:
    """Detect the git hosting username.

    Checks in order:
    1. AUTOPILOT_GIT_USER env var
    2. git config --global autopilot.user
    3. gh CLI (best effort, not required)
    """
    user = os.environ.get("AUTOPILOT_GIT_USER")
    if user:
        return user

    user = _run_cmd(["git", "config", "--global", "autopilot.user"])
    if user:
        return user

    user = _run_cmd(["gh", "api", "user", "-q", ".login"], timeout=10)
    if user:
        return user

    return None


def get_repo_owner(project_path: Path) -> str | None:
    """Extract the owner from a project's git remote origin URL.

    Handles SSH (git@host:owner/repo), HTTPS (https://host/owner/repo),
    and SSH protocol (ssh://git@host/owner/repo) formats for any host.
    """
    url = _run_cmd(["git", "-C", str(project_path), "remote", "get-url", "origin"])
    if not url:
        return None

    # SSH: git@github.com:owner/repo.git
    match = re.match(r"git@[^:]+:([^/]+)/", url)
    if match:
        return match.group(1)

    # HTTPS: https://github.com/owner/repo.git
    match = re.match(r"https?://[^/]+/([^/]+)/", url)
    if match:
        return match.group(1)

    # SSH with protocol: ssh://git@github.com/owner/repo.git
    match = re.match(r"ssh://[^/]+/([^/]+)/", url)
    if match:
        return match.group(1)

    return None
