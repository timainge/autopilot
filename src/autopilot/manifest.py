"""Manifest parsing, loading, and writing."""

import re
from pathlib import Path
from typing import Any

import yaml

from .models import AgentConfig, Manifest, Task

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
    """Parse markdown task checkboxes from content."""
    tasks: list[Task] = []
    task_pattern = re.compile(
        r"^(\s*)-\s+\[([ xX])\]\s+(.+)$", re.MULTILINE
    )

    for match in task_pattern.finditer(content):
        checkbox = match.group(2).strip().lower()
        raw_title = match.group(3).strip()
        line_number = content[: match.start()].count("\n") + 1

        meta: dict[str, str] = {}
        title_clean = raw_title
        for meta_match in re.finditer(r"\[(\w+):\s*([^\]]+)\]", raw_title):
            meta[meta_match.group(1).lower()] = meta_match.group(2).strip()
            title_clean = title_clean.replace(meta_match.group(0), "").strip()

        task_id = meta.get("id", slugify(title_clean))
        depends_str = meta.get("depends", "")
        depends = [d.strip() for d in depends_str.split(",") if d.strip()] if depends_str else []
        attempts = int(meta.get("attempts", "0"))

        status = "done" if checkbox == "x" else "pending"
        # Preserve failed status from inline metadata
        if meta.get("status") == "failed":
            status = "failed"

        tasks.append(Task(
            id=task_id,
            title=title_clean,
            status=status,
            depends=depends,
            attempts=attempts,
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
            checkbox_match = re.match(r"^(\s*)-\s+\[([ xX])\]\s+(.+)$", line)
            if not checkbox_match:
                continue

            raw_title = checkbox_match.group(3).strip()
            clean = re.sub(r"\[(\w+):\s*[^\]]+\]", "", raw_title).strip()
            line_id = slugify(clean)

            id_match = re.search(r"\[id:\s*([^\]]+)\]", raw_title)
            if id_match:
                line_id = id_match.group(1).strip()

            if line_id != task_id:
                continue

            indent = checkbox_match.group(1)
            mark = "x" if new_status == "done" else " "

            # Strip old status/error/attempts metadata
            title_part = re.sub(r"\s*\[status:\s*[^\]]+\]", "", raw_title)
            title_part = re.sub(r"\s*\[error:\s*[^\]]+\]", "", title_part)
            title_part = re.sub(r"\s*\[attempts:\s*[^\]]+\]", "", title_part)

            # Append updated metadata
            if attempts is not None and attempts > 0:
                title_part += f" [attempts: {attempts}]"
            if new_status == "failed" and error:
                short_error = error[:120].replace("\n", " ").replace("]", ")")
                title_part += f" [status: failed] [error: {short_error}]"

            lines[i] = f"{indent}- [{mark}] {title_part}"

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


def discover_projects(scan_dir: Path) -> list[Path]:
    """Find all directories containing a manifest under scan_dir."""
    projects = []
    for child in sorted(scan_dir.iterdir()):
        if child.is_dir() and (child / MANIFEST_DIR / MANIFEST_FILENAME).exists():
            projects.append(child)
    return projects
