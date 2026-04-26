"""Ralph: outer sprint-loop. Per design §7.3, workflows §5.3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autopilot.config import AutopilotConfig
from autopilot.domain.errors import SprintEvaluatorError
from autopilot.domain.goal import Goal
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import Sprint
from autopilot.orchestrator.evaluate import sprint_evaluate
from autopilot.orchestrator.execute import homer
from autopilot.orchestrator.plan import smithers


@dataclass
class RalphOutcome:
    kind: Literal["goals_met", "escalated", "stuck", "max_sprints_hit", "eval_error"]
    sprint: Sprint | None = None
    goal: Goal | None = None


async def ralph(project: Path, cfg: AutopilotConfig) -> RalphOutcome:
    """Outer loop: plan → execute → evaluate until goals are met or we give up."""
    roadmap_path = project / ".dev" / "roadmap.md"

    for _ in range(cfg.max_sprints):
        roadmap = Roadmap.load(roadmap_path)
        goal = roadmap.next_pending_goal()
        if goal is None:
            return RalphOutcome(kind="goals_met")

        sprint = await smithers(project, cfg, goal_id=goal.id)
        if sprint.status == "escalated":
            return RalphOutcome(kind="escalated", sprint=sprint, goal=goal)

        await homer(project, cfg, sprint_id=sprint.id)

        # Reload from disk: homer/smithers mutated these.
        roadmap = Roadmap.load(roadmap_path)
        goal = roadmap.goal(goal.id)
        sprint = Sprint.load(project / ".dev" / "sprints" / sprint.id)

        try:
            verdict = await sprint_evaluate(sprint, goal, roadmap, cfg, project)
        except SprintEvaluatorError:
            # Infra failure in the evaluator — don't loop into another sprint.
            return RalphOutcome(kind="eval_error", sprint=sprint, goal=goal)

        if verdict.achieved:
            goal.mark_achieved(sprint.id, verdict.summary)
            continue
        if sprint.status == "failed":
            return RalphOutcome(kind="stuck", sprint=sprint, goal=goal)
        # Goal still in-progress: persist evaluator feedback and plan another sprint.
        if verdict.feedback:
            sprint.set_closing_evaluator_notes(verdict.feedback)

    return RalphOutcome(kind="max_sprints_hit")
