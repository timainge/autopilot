from dataclasses import dataclass
from typing import Literal, NewType

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
