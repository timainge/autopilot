import re
from dataclasses import dataclass
from typing import Literal, NewType

from autopilot.domain.errors import CLIError

RoadmapId = NewType("RoadmapId", str)
GoalId = NewType("GoalId", str)
SprintId = NewType("SprintId", str)
TaskId = NewType("TaskId", str)
RunId = NewType("RunId", str)
EvalRunId = NewType("EvalRunId", str)


@dataclass(frozen=True)
class EvalRef:
    """Locator for an eval definition: (entity_type, entity_id, eval_index)."""

    entity_type: Literal["roadmap", "goal", "sprint", "task"]
    entity_id: str
    eval_index: int


# Ref grammar per workflows.md §6:
#   <ref> := task:<sprint-id>/<task-id>[#<i>]
#          | sprint:<sprint-id>[#<i>]
#          | goal:<goal-id>[#<i>]
#          | roadmap[#<i>]
_REF_RE = re.compile(
    r"""^
    (?:
        task:(?P<sprint>[A-Za-z0-9_-]+)/(?P<task>[A-Za-z0-9_-]+)
      | sprint:(?P<sprint_only>[A-Za-z0-9_-]+)
      | goal:(?P<goal>[A-Za-z0-9_-]+)
      | roadmap
    )
    (?:\#(?P<idx>\d+))?
    $""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedRef:
    """Result of `_parse_ref(s)`. `eval_index` is None when `#<i>` is omitted."""

    entity_type: Literal["roadmap", "goal", "sprint", "task"]
    entity_id: str  # "" for roadmap; "<sprint>/<task>" for task; id for sprint/goal
    eval_index: int | None


def parse_ref(s: str) -> ParsedRef:
    """Parse a `<ref>` string per workflows.md §6. Raises CLIError on bad input."""
    m = _REF_RE.match(s.strip())
    if not m:
        raise CLIError(reason=f"invalid ref: {s!r}")
    idx_raw = m.group("idx")
    idx = int(idx_raw) if idx_raw is not None else None
    if m.group("sprint") is not None:
        entity_id = f"{m.group('sprint')}/{m.group('task')}"
        return ParsedRef(entity_type="task", entity_id=entity_id, eval_index=idx)
    if m.group("sprint_only") is not None:
        return ParsedRef(entity_type="sprint", entity_id=m.group("sprint_only"), eval_index=idx)
    if m.group("goal") is not None:
        return ParsedRef(entity_type="goal", entity_id=m.group("goal"), eval_index=idx)
    return ParsedRef(entity_type="roadmap", entity_id="", eval_index=idx)
