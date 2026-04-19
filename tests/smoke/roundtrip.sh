#!/usr/bin/env bash
# Stage C smoke: save → load → save produces byte-identical files for every entity.
# Per design §6.3: "save→load→save produces identical bytes."
set -euo pipefail

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

cd "$(dirname "$0")/../.."

uv run python - "$TMPDIR" <<'PY'
import sys
from datetime import datetime, timezone
from pathlib import Path

from autopilot.domain.eval import Eval, EvalRun
from autopilot.domain.goal import Goal
from autopilot.domain.ids import EvalRef, EvalRunId, SprintId
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import RevisionRecord, Sprint
from autopilot.domain.task import AttemptRecord, Task

tmp = Path(sys.argv[1])


def assert_bytes_equal(a: Path, b: Path, label: str) -> None:
    ba, bb = a.read_bytes(), b.read_bytes()
    if ba != bb:
        print(f"FAIL: {label} bytes differ", file=sys.stderr)
        print(f"--- {a} ---", file=sys.stderr)
        sys.stderr.write(ba.decode("utf-8", errors="replace"))
        print(f"--- {b} ---", file=sys.stderr)
        sys.stderr.write(bb.decode("utf-8", errors="replace"))
        sys.exit(1)
    print(f"OK: {label}")


def roundtrip(entity, first: Path, second: Path) -> None:
    # first save already happened via caller
    loaded_cls = type(entity).load
    if hasattr(type(entity), "_dir"):
        # Sprint uses directory-based loader; handled separately by caller.
        raise AssertionError("call sprint_roundtrip for Sprint")
    reloaded = loaded_cls(first)
    reloaded._path = second
    reloaded._save()


# ---------- Task ----------
started = datetime(2026, 4, 19, 10, 14, 33, tzinfo=timezone.utc)
completed = datetime(2026, 4, 19, 10, 14, 41, tzinfo=timezone.utc)
task = Task(
    id="001",
    intent="# Task 001\n\nDo the thing.",
    status="completed",
    depends_on=["000"],
    eval=[Eval(type="shell", run="pytest tests/test_auth.py")],
    attempts=[AttemptRecord(started_at=started, completed_at=completed)],
    summary="Did the thing.",
)
t1 = tmp / "task-001.md"
t2 = tmp / "task-001.copy.md"
task._path = t1
task._save()
loaded_task = Task.load(t1)
loaded_task._path = t2
loaded_task._save()
assert_bytes_equal(t1, t2, "Task")

# ---------- Goal ----------
goal = Goal(
    id="ship-v0.1.0",
    intent="# Goal: Ship v0.1.0\n\nPublish to PyPI.",
    priority=1,
    status="in-progress",
    eval=[Eval(type="shell", run="pip install autopilot && autopilot --version")],
    achieved_by=[SprintId("sprint-001")],
    summary=None,
)
g1 = tmp / "goal-ship-v0.1.0.md"
g2 = tmp / "goal-ship-v0.1.0.copy.md"
goal._path = g1
goal._save()
loaded_goal = Goal.load(g1)
loaded_goal._path = g2
loaded_goal._save()
assert_bytes_equal(g1, g2, "Goal")

# ---------- Sprint (dir-based, two tasks) ----------
sprint_dir_a = tmp / "sprints" / "sprint-001"
sprint_dir_b = tmp / "sprints-copy" / "sprint-001"
sprint_dir_a.mkdir(parents=True)
sprint_dir_b.mkdir(parents=True)

task_a = Task(id="001", intent="# Task 001\n\nFirst task body.", status="pending")
task_b = Task(
    id="002",
    intent="# Task 002\n\nSecond task body.",
    status="pending",
    depends_on=["001"],
)
sprint = Sprint(
    id="sprint-001",
    primary_goal="ship-v0.1.0",
    context="# Sprint 001\n\nSprint context narrative.",
    tasks=[task_a, task_b],
    status="approved",
    revision_rounds=[
        RevisionRecord(critic_notes="looks good", judge_verdict="READY", feedback="")
    ],
    summary=None,
)
sprint._dir = sprint_dir_a
task_a._path = sprint_dir_a / "task-001.md"
task_b._path = sprint_dir_a / "task-002.md"
sprint._save()
task_a._save()
task_b._save()

loaded_sprint = Sprint.load(sprint_dir_a)
loaded_sprint._dir = sprint_dir_b
for t in loaded_sprint.tasks:
    t._path = sprint_dir_b / t._path.name
loaded_sprint._save()
for t in loaded_sprint.tasks:
    t._save()

assert_bytes_equal(
    sprint_dir_a / "sprint-001.md", sprint_dir_b / "sprint-001.md", "Sprint file"
)
assert_bytes_equal(
    sprint_dir_a / "task-001.md", sprint_dir_b / "task-001.md", "Sprint task-001"
)
assert_bytes_equal(
    sprint_dir_a / "task-002.md", sprint_dir_b / "task-002.md", "Sprint task-002"
)

# ---------- Roadmap (+ goals dir) ----------
rm_root_a = tmp / "roadmap_a"
rm_root_b = tmp / "roadmap_b"
(rm_root_a / "goals").mkdir(parents=True)
(rm_root_b / "goals").mkdir(parents=True)

g_inner = Goal(
    id="ship-v0.1.0",
    intent="# Goal: Ship\n\nPublish.",
    priority=1,
    status="pending",
)
g_inner._path = rm_root_a / "goals" / "goal-ship-v0.1.0.md"
g_inner._save()

rm = Roadmap(
    archetype="python-cli",
    eval=[Eval(type="shell", run="pytest && ruff check src/")],
    narrative="# Roadmap\n\nNarrative body.\n\n## Goals\n\n1. Ship.",
    goals=[],
)
rm._path = rm_root_a / "roadmap.md"
rm._save()

loaded_rm = Roadmap.load(rm_root_a / "roadmap.md")
# Copy goals across
for g in loaded_rm.goals:
    g._path = rm_root_b / "goals" / g._path.name
    g._save()
loaded_rm._path = rm_root_b / "roadmap.md"
loaded_rm._save()

assert_bytes_equal(
    rm_root_a / "roadmap.md", rm_root_b / "roadmap.md", "Roadmap file"
)
assert_bytes_equal(
    rm_root_a / "goals" / "goal-ship-v0.1.0.md",
    rm_root_b / "goals" / "goal-ship-v0.1.0.md",
    "Roadmap inner goal",
)

# ---------- EvalRun ----------
runs_dir = tmp / "eval-runs"
runs_dir.mkdir()
run = EvalRun(
    id=EvalRunId("evalrun-2026-04-19-001"),
    eval_ref=EvalRef(entity_type="task", entity_id="sprint-001/task-001", eval_index=0),
    eval_snapshot={"type": "shell", "run": "pytest -x"},
    started_at=datetime(2026, 4, 19, 10, 14, 33, tzinfo=timezone.utc),
    completed_at=datetime(2026, 4, 19, 10, 14, 41, tzinfo=timezone.utc),
    status="passed",
    score=None,
    output="all tests passed\n3 passed in 0.42s",
    cost_usd=0.0,
    context_digest="sha256:abcd1234",
)
e1 = runs_dir / "evalrun-2026-04-19-001.md"
e2 = runs_dir / "evalrun-2026-04-19-001.copy.md"
run._path = e1
run._save()
loaded_run = EvalRun.load(e1)
loaded_run._path = e2
loaded_run._save()
assert_bytes_equal(e1, e2, "EvalRun")

print("ALL ROUNDTRIPS PASS")
PY
