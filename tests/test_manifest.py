"""Unit tests for autopilot.manifest functions."""

from pathlib import Path

import pytest

from autopilot.manifest import (
    get_next_task,
    get_task_summary,
    load_manifest,
    parse_frontmatter,
    parse_tasks,
    slugify,
)
from autopilot.models import Manifest, Task

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    # / is treated as a word separator → becomes a dash between words
    result = slugify("Add user/auth & tests!")
    assert "user" in result
    assert "auth" in result
    assert "tests" in result
    assert "&" not in result
    assert "!" not in result


def test_slugify_path_separators():
    # / and . are treated as word separators
    result = slugify("src/foo/bar.py")
    assert result.startswith("src")
    assert "foo" in result
    assert "bar" in result
    assert "/" not in result
    assert "." not in result


def test_slugify_truncation():
    long_text = "a" * 80
    result = slugify(long_text)
    assert len(result) <= 60


def test_slugify_strips_leading_trailing_dashes():
    result = slugify("  --hello--  ")
    assert not result.startswith("-")
    assert not result.endswith("-")


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_basic():
    content = "---\nname: My Project\napproved: true\n---\n# Body"
    fm, body = parse_frontmatter(content)
    assert fm["name"] == "My Project"
    assert fm["approved"] is True
    assert "Body" in body


def test_parse_frontmatter_no_frontmatter():
    content = "# Just a markdown file\nNo frontmatter here."
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert "Just a markdown file" in body


def test_parse_frontmatter_malformed_yaml():
    content = "---\n: bad: yaml: here:\n---\n# Body"
    fm, body = parse_frontmatter(content)
    assert fm == {}


def test_parse_frontmatter_empty_frontmatter():
    content = "---\n---\n# Body"
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert "Body" in body


# ---------------------------------------------------------------------------
# parse_tasks
# ---------------------------------------------------------------------------

SAMPLE_TASKS = """\
---
name: Test
---

### [ ] setup-project
Install dependencies and configure the environment.

### [x] write-tests [depends: setup-project]
Write unit tests.

### [ ] deploy [status: failed] [attempts: 3] [depends: write-tests]
Deploy to production.
"""


def test_parse_tasks_count():
    tasks = parse_tasks(SAMPLE_TASKS)
    assert len(tasks) == 3


def test_parse_tasks_ids():
    tasks = parse_tasks(SAMPLE_TASKS)
    ids = [t.id for t in tasks]
    assert "setup-project" in ids
    assert "write-tests" in ids
    assert "deploy" in ids


def test_parse_tasks_status_pending():
    tasks = parse_tasks(SAMPLE_TASKS)
    setup = next(t for t in tasks if t.id == "setup-project")
    assert setup.status == "pending"


def test_parse_tasks_status_done():
    tasks = parse_tasks(SAMPLE_TASKS)
    write = next(t for t in tasks if t.id == "write-tests")
    assert write.status == "done"


def test_parse_tasks_status_failed():
    tasks = parse_tasks(SAMPLE_TASKS)
    deploy = next(t for t in tasks if t.id == "deploy")
    assert deploy.status == "failed"


def test_parse_tasks_depends():
    tasks = parse_tasks(SAMPLE_TASKS)
    write = next(t for t in tasks if t.id == "write-tests")
    assert "setup-project" in write.depends
    deploy = next(t for t in tasks if t.id == "deploy")
    assert "write-tests" in deploy.depends


def test_parse_tasks_attempts():
    tasks = parse_tasks(SAMPLE_TASKS)
    deploy = next(t for t in tasks if t.id == "deploy")
    assert deploy.attempts == 3


def test_parse_tasks_body():
    tasks = parse_tasks(SAMPLE_TASKS)
    setup = next(t for t in tasks if t.id == "setup-project")
    assert "Install dependencies" in setup.body


def test_parse_tasks_empty():
    assert parse_tasks("No tasks here.") == []


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------

FULL_MANIFEST = """\
---
name: My Project
approved: true
status: active
max_task_attempts: 2
---

### [ ] task-one
Do something.

### [x] task-two [depends: task-one]
Done already.
"""


def test_load_manifest_full(tmp_path: Path):
    dev = tmp_path / ".dev"
    dev.mkdir()
    (dev / "autopilot.md").write_text(FULL_MANIFEST)

    manifest = load_manifest(tmp_path)
    assert manifest is not None
    assert manifest.name == "My Project"
    assert manifest.approved is True
    assert manifest.status == "active"
    assert manifest.max_task_attempts == 2
    assert len(manifest.tasks) == 2


def test_load_manifest_missing(tmp_path: Path):
    assert load_manifest(tmp_path) is None


def test_load_manifest_no_frontmatter_defaults(tmp_path: Path):
    dev = tmp_path / ".dev"
    dev.mkdir()
    (dev / "autopilot.md").write_text("### [ ] only-task\nDo it.\n")

    manifest = load_manifest(tmp_path)
    assert manifest is not None
    assert manifest.approved is False
    assert manifest.status == "pending"
    assert manifest.max_task_attempts == 3
    assert manifest.name == tmp_path.name


# ---------------------------------------------------------------------------
# get_next_task
# ---------------------------------------------------------------------------


def _make_manifest(tasks: list[Task], max_attempts: int = 3) -> Manifest:
    return Manifest(
        path=Path("/fake/path"),
        name="test",
        tasks=tasks,
        max_task_attempts=max_attempts,
    )


def test_get_next_task_simple():
    tasks = [Task(id="a", title="a", status="pending")]
    manifest = _make_manifest(tasks)
    assert get_next_task(manifest).id == "a"


def test_get_next_task_skips_done():
    tasks = [
        Task(id="a", title="a", status="done"),
        Task(id="b", title="b", status="pending"),
    ]
    manifest = _make_manifest(tasks)
    assert get_next_task(manifest).id == "b"


def test_get_next_task_blocked_by_dependency():
    tasks = [
        Task(id="a", title="a", status="pending"),
        Task(id="b", title="b", status="pending", depends=["a"]),
    ]
    manifest = _make_manifest(tasks)
    # b is blocked; a should be returned
    assert get_next_task(manifest).id == "a"


def test_get_next_task_dependency_satisfied():
    tasks = [
        Task(id="a", title="a", status="done"),
        Task(id="b", title="b", status="pending", depends=["a"]),
    ]
    manifest = _make_manifest(tasks)
    assert get_next_task(manifest).id == "b"


def test_get_next_task_skips_max_attempts():
    tasks = [Task(id="a", title="a", status="pending", attempts=3)]
    manifest = _make_manifest(tasks, max_attempts=3)
    assert get_next_task(manifest) is None


def test_get_next_task_none_when_all_done():
    tasks = [Task(id="a", title="a", status="done")]
    manifest = _make_manifest(tasks)
    assert get_next_task(manifest) is None


# ---------------------------------------------------------------------------
# get_task_summary
# ---------------------------------------------------------------------------


def test_get_task_summary_counts():
    tasks = [
        Task(id="a", title="a", status="done"),
        Task(id="b", title="b", status="done"),
        Task(id="c", title="c", status="pending"),
        Task(id="d", title="d", status="failed"),
    ]
    manifest = _make_manifest(tasks)
    summary = get_task_summary(manifest)
    assert "2/4 done" in summary
    assert "1 pending" in summary
    assert "1 failed" in summary


def test_get_task_summary_empty():
    manifest = _make_manifest([])
    summary = get_task_summary(manifest)
    assert "0/0" in summary
