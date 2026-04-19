"""Unit test at the serialization boundary — ref grammar per workflows.md §6.

This is the ONE new unit test added for Phase 2 §2.2. It covers every case in
the grammar:

    <ref> := task:<sprint-id>/<task-id>[#<i>]
           | sprint:<sprint-id>[#<i>]
           | goal:<goal-id>[#<i>]
           | roadmap[#<i>]
"""

from __future__ import annotations

import pytest

from autopilot.domain.errors import CLIError
from autopilot.domain.ids import parse_ref


def test_task_ref_with_index() -> None:
    r = parse_ref("task:sprint-001/task-003#0")
    assert r.entity_type == "task"
    assert r.entity_id == "sprint-001/task-003"
    assert r.eval_index == 0


def test_task_ref_without_index() -> None:
    r = parse_ref("task:sprint-007/task-042")
    assert r.entity_type == "task"
    assert r.entity_id == "sprint-007/task-042"
    assert r.eval_index is None


def test_sprint_ref_with_index() -> None:
    r = parse_ref("sprint:sprint-001#2")
    assert r.entity_type == "sprint"
    assert r.entity_id == "sprint-001"
    assert r.eval_index == 2


def test_sprint_ref_without_index() -> None:
    r = parse_ref("sprint:sprint-001")
    assert r.entity_type == "sprint"
    assert r.entity_id == "sprint-001"
    assert r.eval_index is None


def test_goal_ref_with_index() -> None:
    r = parse_ref("goal:ship-v0-1-0#1")
    assert r.entity_type == "goal"
    assert r.entity_id == "ship-v0-1-0"
    assert r.eval_index == 1


def test_goal_ref_without_index() -> None:
    r = parse_ref("goal:greet-works")
    assert r.entity_type == "goal"
    assert r.entity_id == "greet-works"
    assert r.eval_index is None


def test_roadmap_ref_with_index() -> None:
    r = parse_ref("roadmap#0")
    assert r.entity_type == "roadmap"
    assert r.entity_id == ""
    assert r.eval_index == 0


def test_roadmap_ref_without_index() -> None:
    r = parse_ref("roadmap")
    assert r.entity_type == "roadmap"
    assert r.entity_id == ""
    assert r.eval_index is None


def test_whitespace_is_stripped() -> None:
    r = parse_ref("  sprint:sprint-001#0  ")
    assert r.entity_type == "sprint"
    assert r.eval_index == 0


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "task:sprint-001",  # task requires /<task-id>
        "task:/task-001",  # missing sprint id
        "sprint:",  # missing id
        "goal:",
        "roadmaps",  # not exactly `roadmap`
        "foo:bar",  # unknown prefix
        "roadmap#abc",  # non-numeric index
        "sprint:sprint-001#",  # empty index
    ],
)
def test_bad_refs_raise(bad: str) -> None:
    with pytest.raises(CLIError):
        parse_ref(bad)


def test_task_ref_index_parses_as_int() -> None:
    r = parse_ref("task:s1/t1#42")
    assert r.eval_index == 42
