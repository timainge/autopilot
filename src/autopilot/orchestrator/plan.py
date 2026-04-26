"""Smithers: sprint planning loop. Per design §7.2."""

from __future__ import annotations

import re
from pathlib import Path

from autopilot.agents.prompts import (
    build_critic_prompt,
    build_judge_prompt,
    build_planner_prompt,
)
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.clock import now
from autopilot.domain.errors import ParseError, ValidationError
from autopilot.domain.goal import Goal
from autopilot.domain.parse import parse_sprint, parse_verdict
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import RevisionRecord, Sprint

_FILE_HEADER_RE = re.compile(r"^###\s+FILE:\s*(?P<name>\S+?)\s*$", re.MULTILINE)


def next_sprint_id(project: Path) -> str:
    """Scan `.dev/sprints/` for existing `sprint-NNN` dirs; return next zero-padded id."""
    sprints_dir = project / ".dev" / "sprints"
    existing: list[int] = []
    if sprints_dir.is_dir():
        for p in sprints_dir.glob("sprint-*"):
            if not p.is_dir():
                continue
            tail = p.name[len("sprint-") :]
            try:
                existing.append(int(tail))
            except ValueError:
                continue
    nxt = (max(existing) + 1) if existing else 1
    return f"sprint-{nxt:03d}"


def _load_prior_sprints(project: Path) -> list[Sprint]:
    sprints_dir = project / ".dev" / "sprints"
    if not sprints_dir.is_dir():
        return []
    out: list[Sprint] = []
    for p in sorted(sprints_dir.glob("sprint-*")):
        if not p.is_dir():
            continue
        try:
            out.append(Sprint.load(p))
        except (ParseError, ValidationError):
            # Legible-but-unparseable sprints shouldn't block planning.
            continue
    return out


def _load_research(project: Path) -> str | None:
    research_dir = project / ".dev" / "research"
    if not research_dir.is_dir():
        return None
    parts: list[str] = []
    for p in sorted(research_dir.glob("*.md")):
        parts.append(f"# {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
    if not parts:
        return None
    return "\n\n".join(parts)


def _parse_planner_output(text: str) -> tuple[str, list[str]]:
    """Split planner output into (sprint_text, [task_text, ...]) on `### FILE:` headers.

    Convention: each file block starts with `### FILE: <name>` on its own line.
    The first block whose name matches `sprint-*.md` is the sprint; the rest
    (ordered by name) are tasks. Raises ParseError if no FILE headers found.
    """
    matches = list(_FILE_HEADER_RE.finditer(text))
    if not matches:
        raise ParseError(
            file_path=Path("<planner-output>"),
            line_number=None,
            reason="planner output missing '### FILE: ...' headers",
        )
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        name = m.group("name")
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].lstrip("\n").rstrip() + "\n"
        blocks.append((name, body))

    sprint_text: str | None = None
    task_blocks: list[tuple[str, str]] = []
    for name, body in blocks:
        if name.startswith("sprint-") and name.endswith(".md") and sprint_text is None:
            sprint_text = body
        else:
            task_blocks.append((name, body))
    if sprint_text is None:
        raise ParseError(
            file_path=Path("<planner-output>"),
            line_number=None,
            reason="planner output missing a sprint-NNN.md block",
        )
    task_blocks.sort(key=lambda kv: kv[0])
    return sprint_text, [b for _, b in task_blocks]


def _synthesise_escalated_sprint(
    sprint_id: str,
    primary_goal: str,
    rounds: list[RevisionRecord],
    reason: str,
) -> Sprint:
    """Build a placeholder Sprint carrying revision history when planning fails.

    Used when the planner produced at least one parseable draft but the judge
    never said READY — so we have a real sprint to persist as escalated.
    """
    # A minimal task placeholder is required by Sprint's invariants.
    from autopilot.domain.task import Task

    placeholder = Task(
        id="001",
        intent=f"# Escalated\n\n{reason}",
        status="failed",
        summary=reason,
    )
    return Sprint(
        id=sprint_id,
        primary_goal=primary_goal,
        context=f"# {sprint_id} (escalated)\n\n{reason}",
        tasks=[placeholder],
        status="planning",
        revision_rounds=rounds,
    )


async def smithers(
    project: Path,
    cfg: AutopilotConfig,
    *,
    goal_id: str | None = None,
) -> Sprint:
    """Plan → critique → judge loop. Returns an approved or escalated Sprint."""
    roadmap = Roadmap.load(project / ".dev" / "roadmap.md")
    goal: Goal | None
    if goal_id is not None:
        goal = roadmap.goal(goal_id)
    else:
        goal = roadmap.next_pending_goal()
    if goal is None:
        raise ValidationError(
            entity_type="roadmap",
            entity_id=None,
            field="goals",
            reason="no pending goal available to plan",
        )

    prior_sprints = _load_prior_sprints(project)
    research = _load_research(project)
    sprint_id = next_sprint_id(project)
    sprint_dir = project / ".dev" / "sprints" / sprint_id

    # Pull the most-recent prior sprint targeting this goal — if it carried
    # closing evaluator notes, surface them so the planner can remediate.
    evaluator_feedback: str | None = None
    for s in reversed(prior_sprints):
        if s.primary_goal == goal.id and s.closing_evaluator_notes:
            evaluator_feedback = s.closing_evaluator_notes
            break

    feedback: str | None = None
    rounds: list[RevisionRecord] = []
    last_sprint: Sprint | None = None

    total_rounds = 1 + cfg.max_judge_rounds
    for _round in range(total_rounds):
        planner_result = await run_agent(
            "planner",
            build_planner_prompt(
                roadmap,
                goal,
                prior_sprints,
                research,
                feedback,
                evaluator_feedback=evaluator_feedback,
            ),
            cfg,
            cwd=project,
        )
        if not planner_result.success:
            feedback = f"planner call failed: {planner_result.error or 'unknown error'}"
            rounds.append(
                RevisionRecord(
                    critic_notes="",
                    judge_verdict="ERROR",
                    feedback=feedback,
                    timestamp=now(),
                )
            )
            continue

        try:
            sprint_text, task_texts = _parse_planner_output(planner_result.output)
            # Orchestrator authoritative for id (filesystem slot we reserved)
            # and primary_goal — override planner frontmatter at parse time so
            # the final Sprint is constructed with authoritative values.
            sprint_draft = parse_sprint(
                sprint_text,
                task_texts,
                expected_id=sprint_id,
                expected_primary_goal=goal.id,
            )
        except (ParseError, ValidationError) as e:
            feedback = f"planner output failed to parse: {e}"
            rounds.append(
                RevisionRecord(
                    critic_notes="",
                    judge_verdict="PARSE_ERROR",
                    feedback=feedback,
                    timestamp=now(),
                )
            )
            continue

        last_sprint = sprint_draft

        critic_result = await run_agent(
            "critic", build_critic_prompt(sprint_draft, goal), cfg, cwd=project
        )
        critic_notes = (
            critic_result.output
            if critic_result.success
            else (f"critic call failed: {critic_result.error}")
        )

        judge_result = await run_agent(
            "judge",
            build_judge_prompt(sprint_draft, goal, critic_notes),
            cfg,
            cwd=project,
        )
        if not judge_result.success:
            feedback = f"judge call failed: {judge_result.error or 'unknown error'}"
            rounds.append(
                RevisionRecord(
                    critic_notes=critic_notes,
                    judge_verdict="ERROR",
                    feedback=feedback,
                    timestamp=now(),
                )
            )
            continue
        verdict = parse_verdict(judge_result.output)

        rounds.append(
            RevisionRecord(
                critic_notes=critic_notes,
                judge_verdict="READY" if verdict.ready else "NOT_READY",
                feedback=verdict.feedback,
                timestamp=now(),
            )
        )

        if verdict.ready:
            sprint_draft.revision_rounds = list(rounds)
            sprint_draft._dir = sprint_dir
            sprint_dir.mkdir(parents=True, exist_ok=True)
            sprint_draft._save()
            for task in sprint_draft.tasks:
                task._path = sprint_dir / f"task-{task.id}.md"
                task._save()
            sprint_draft.approve()
            goal.mark_in_progress(sprint_draft.id)
            return sprint_draft

        # NOT_READY: feed both the judge's verdict feedback AND the critic's
        # notes into the next planner round. The judge gates; the critic
        # coaches the planner. Both signals carry information the planner
        # needs to produce a better revision.
        feedback_parts: list[str] = []
        if verdict.feedback:
            feedback_parts.append(f"--- JUDGE FEEDBACK ---\n{verdict.feedback}")
        if critic_notes:
            feedback_parts.append(f"--- CRITIC NOTES ---\n{critic_notes}")
        feedback = "\n\n".join(feedback_parts) if feedback_parts else None

    # Max rounds exhausted: persist best-effort escalated sprint so disk is legible.
    if last_sprint is not None:
        last_sprint.revision_rounds = list(rounds)
        last_sprint._dir = sprint_dir
        sprint_dir.mkdir(parents=True, exist_ok=True)
        last_sprint._save()
        for task in last_sprint.tasks:
            task._path = sprint_dir / f"task-{task.id}.md"
            task._save()
        last_sprint.escalate("judge did not reach READY within max_judge_rounds")
        return last_sprint

    # Never got a parseable sprint: synthesise a minimal one so state is legible.
    synth = _synthesise_escalated_sprint(
        sprint_id,
        goal.id,
        rounds,
        "planner never produced a parseable sprint within max_judge_rounds",
    )
    synth._dir = sprint_dir
    sprint_dir.mkdir(parents=True, exist_ok=True)
    synth._save()
    for task in synth.tasks:
        task._path = sprint_dir / f"task-{task.id}.md"
        task._save()
    synth.escalate("planner never produced a parseable sprint within max_judge_rounds")
    return synth
