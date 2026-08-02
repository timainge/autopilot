"""Autopilot CLI entry point. Per workflows §6."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from autopilot.config import AutopilotConfig, load_config
from autopilot.domain.errors import CLIError
from autopilot.domain.ids import parse_ref as _parse_ref
from autopilot.log import emit

# Re-exported for tests / external callers.
__all__ = ["main", "_parse_ref", "_find_project_root"]

# `### FILE: <name>` envelope used by planner + roadmap outputs.
_FILE_HEADER_RE = re.compile(r"^###\s+FILE:\s*(?P<name>\S+?)\s*$", re.MULTILINE)


def _find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or cwd) to find a dir containing `.dev/roadmap.md`."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".dev" / "roadmap.md").is_file():
            return candidate
    raise CLIError(reason=f"could not find `.dev/roadmap.md` in {cur} or any parent directory")


def _resolve_project(arg: str | None) -> Path:
    if arg:
        p = Path(arg).resolve()
        if not (p / ".dev" / "roadmap.md").is_file():
            raise CLIError(reason=f"no `.dev/roadmap.md` at {p}")
        return p
    return _find_project_root()


def _resolve_project_loose(arg: str | None) -> Path:
    """Like `_resolve_project` but allows a project without a roadmap yet.

    Used by `roadmap create` — the command whose job is to write the roadmap.
    """
    if arg:
        p = Path(arg).resolve()
        if not p.is_dir():
            raise CLIError(reason=f"project path does not exist: {p}")
        return p
    return Path.cwd().resolve()


def _split_file_blocks(text: str) -> list[tuple[str, str]]:
    """Split text on `### FILE: <name>` headers. Returns [(name, body), ...].

    Raises CLIError if no FILE headers are found.
    """
    matches = list(_FILE_HEADER_RE.finditer(text))
    if not matches:
        raise CLIError(reason="agent output missing '### FILE: ...' envelope headers")
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        name = m.group("name")
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].lstrip("\n").rstrip() + "\n"
        blocks.append((name, body))
    return blocks


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autopilot", description="Autopilot CLI")
    p.add_argument("--verbose", action="store_true", help="emit JSONL log lines to stderr")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _proj(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("project", nargs="?", default=None)

    sp = sub.add_parser("ralph", help="build loop: plan/execute/evaluate until goals met")
    _proj(sp)

    sp = sub.add_parser("analyse", help="analyse a topic, write to .dev/analysis/")
    _proj(sp)
    sp.add_argument("--topic", default="general")

    sp = sub.add_parser("lisa", help="research loop: brief → enquiries → report")
    _proj(sp)
    brief_group = sp.add_mutually_exclusive_group(required=True)
    brief_group.add_argument("--brief", default=None, help="path to brief file")
    brief_group.add_argument("--brief-text", default=None, help="brief inline as a string")
    sp.add_argument("--slug", default=None)
    sp.add_argument("--max-iterations", dest="max_iterations", type=int, default=None)

    roadmap = sub.add_parser("roadmap", help="roadmap operations")
    roadmap_sub = roadmap.add_subparsers(dest="subcmd", required=True)
    sp = roadmap_sub.add_parser("create", help="create .dev/roadmap.md + goals")
    _proj(sp)
    sp.add_argument("--research", default=None)
    sp = roadmap_sub.add_parser("revise", help="revise an existing .dev/roadmap.md")
    _proj(sp)

    sprint = sub.add_parser("sprint", help="sprint sub-commands")
    sprint_sub = sprint.add_subparsers(dest="subcmd", required=True)
    sp = sprint_sub.add_parser("plan", help="planner-only sprint draft")
    _proj(sp)
    sp.add_argument("--goal", dest="goal_id", default=None)
    sp = sprint_sub.add_parser("prepare", help="plan + critique + judge to approval")
    _proj(sp)
    sp.add_argument("--goal", dest="goal_id", default=None)
    sp = sprint_sub.add_parser("critique", help="append critic revision_round to sprint")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("judge", help="append judge verdict to sprint")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("evaluate", help="run goal evals + evaluator")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("execute", help="execute the approved sprint")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)

    task = sub.add_parser("task", help="task operations")
    task_sub = task.add_subparsers(dest="subcmd", required=True)
    sp = task_sub.add_parser("run", help="run one task with retries")
    sp.add_argument("task_file")
    sp = task_sub.add_parser("retry", help="retry a failed task")
    sp.add_argument("task_file")

    frink = sub.add_parser("frink", help="experiment loop: rubric-frozen laps until done")
    frink_sub = frink.add_subparsers(dest="subcmd", required=True)
    sp = frink_sub.add_parser("start", help="start (or resume) an experiment")
    _proj(sp)
    sp.add_argument("--mode", required=True, choices=["build", "tune", "research"])
    sp.add_argument("--objective", required=True, help="objective text, or @file.md")
    sp.add_argument("--rubric", required=True, help="frozen rubric text, or @file.md")
    sp.add_argument("--goal", dest="goal_id", default=None)
    sp.add_argument("--hil", action="store_true", help="human-in-the-loop verdict approval")
    sp = frink_sub.add_parser("status", help="print experiment frontmatter + laps + cost")
    _proj(sp)
    sp.add_argument("exp_id", nargs="?", default=None)
    sp = frink_sub.add_parser("review", help="re-run the reviewer on an experiment")
    _proj(sp)
    sp.add_argument("exp_id", nargs="?", default=None)

    study = sub.add_parser("study", help="matrix validation: fixed cells, frozen scorer, no judge")
    study_sub = study.add_subparsers(dest="subcmd", required=True)
    sp = study_sub.add_parser("run", help="run (or resume) a study from a spec file")
    _proj(sp)
    sp.add_argument(
        "--spec", required=True, help="path to study spec (matrix/run/scorer + objective)"
    )
    sp = study_sub.add_parser("status", help="print study frontmatter + cells")
    _proj(sp)
    sp.add_argument("study_id", nargs="?", default=None)
    sp = study_sub.add_parser("report", help="re-run the analyst on a study")
    _proj(sp)
    sp.add_argument("study_id", nargs="?", default=None)

    eval_ = sub.add_parser("eval", help="eval inspection / manual execution")
    eval_sub = eval_.add_subparsers(dest="subcmd", required=True)
    sp = eval_sub.add_parser("show", help="print eval payload to stdout")
    sp.add_argument("ref")
    sp = eval_sub.add_parser("run", help="execute eval(s), write EvalRun file(s)")
    sp.add_argument("ref")

    return p


# ---------- loop commands ----------


async def _cmd_sprint_prepare(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.plan import sprint_prepare

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint = await sprint_prepare(project, cfg, goal_id=args.goal_id)
    print(f"{sprint.id} {sprint.status}")
    return 0 if sprint.status == "approved" else 1


async def _cmd_sprint_execute(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.execute import sprint_execute

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint = await sprint_execute(project, cfg, sprint_id=args.sprint_id)
    print(f"{sprint.id} {sprint.status}")
    return 0 if sprint.status == "completed" else 1


async def _cmd_ralph(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.ralph import ralph

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    outcome = await ralph(project, cfg)
    print(f"ralph: {outcome.kind}")
    return 0 if outcome.kind == "goals_met" else 1


async def _cmd_sprint_evaluate(args: argparse.Namespace) -> int:
    from autopilot.domain.errors import SprintEvaluatorError
    from autopilot.domain.roadmap import Roadmap
    from autopilot.domain.sprint import Sprint
    from autopilot.orchestrator.evaluate import sprint_evaluate
    from autopilot.orchestrator.execute import _latest_sprint_dir

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    if args.sprint_id:
        sprint_dir = project / ".dev" / "sprints" / args.sprint_id
    else:
        sprint_dir = _latest_sprint_dir(project)
        if sprint_dir is None:
            raise CLIError(reason="no sprints found")
    sprint = Sprint.load(sprint_dir)
    roadmap = Roadmap.load(project / ".dev" / "roadmap.md")
    goal = roadmap.goal(sprint.primary_goal)
    try:
        verdict = await sprint_evaluate(sprint, goal, roadmap, cfg, project)
    except SprintEvaluatorError as e:
        raise CLIError(reason=str(e)) from e
    print(f"achieved={verdict.achieved}: {verdict.summary}")
    return 0 if verdict.achieved else 1


# ---------- analyse ----------


async def _cmd_lisa(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.research_loop import lisa

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    if args.brief is not None:
        bp = Path(args.brief)
        if not bp.is_file():
            raise CLIError(reason=f"brief file not found: {bp}")
        brief = bp.read_text(encoding="utf-8")
    else:
        brief = args.brief_text
    if not brief or not brief.strip():
        raise CLIError(reason="brief is empty")
    run = await lisa(
        project,
        cfg,
        brief,
        slug=args.slug,
        max_iterations=args.max_iterations,
    )
    print(f"{run.slug} {run.status}")
    return 0 if run.status == "satisfied" else 1


async def _cmd_analyse(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_analyst_prompt
    from autopilot.agents.runner import run_agent
    from autopilot.domain.persists import atomic_write

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    topic = args.topic or "general"
    analysis_dir = project / ".dev" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out_path = analysis_dir / f"{topic}.md"

    result = await run_agent("analyst", build_analyst_prompt(topic, project), cfg, cwd=project)
    if not result.success:
        raise CLIError(reason=f"analyst call failed: {result.error or 'unknown error'}")
    atomic_write(out_path, result.output)
    print(f"wrote {out_path}")
    return 0


def _arg_or_file(value: str) -> str:
    """`@path` reads the file; anything else is literal text."""
    if value.startswith("@"):
        fp = Path(value[1:])
        if not fp.is_file():
            raise CLIError(reason=f"file not found: {fp}")
        return fp.read_text(encoding="utf-8")
    return value


def _resolve_experiment_dir(project: Path, exp_id: str | None) -> Path:
    root = project / ".dev" / "experiments"
    if exp_id:
        d = root / exp_id
        if not (d / f"{exp_id}.md").is_file():
            raise CLIError(reason=f"no experiment at {d}")
        return d
    candidates = sorted(d for d in root.glob("exp-*") if (d / f"{d.name}.md").is_file())
    if not candidates:
        raise CLIError(reason=f"no experiments under {root}")
    return candidates[-1]


async def _cmd_frink_start(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.frink import frink

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    outcome = await frink(
        project,
        cfg,
        mode=args.mode,
        objective=_arg_or_file(args.objective),
        rubric=_arg_or_file(args.rubric),
        hil_required=args.hil,
        goal_id=args.goal_id,
    )
    exp = outcome.experiment
    print(f"{exp.id} {exp.status} laps={len(exp.laps)} cost=${exp.cost_usd:.2f}")
    return 0 if exp.status == "completed" else 1


async def _cmd_frink_status(args: argparse.Namespace) -> int:
    from autopilot.domain.experiment import Experiment

    project = _resolve_project_loose(args.project)
    exp = Experiment.load(_resolve_experiment_dir(project, args.exp_id))
    print(f"id: {exp.id}")
    print(f"mode: {exp.mode}")
    print(f"status: {exp.status}")
    print(f"cost_usd: {exp.cost_usd:.2f}")
    print(f"laps: {len(exp.laps)}")
    for lap in exp.laps[-5:]:
        reason = (lap.verdict_reason or "").replace("\n", " ")[:120]
        print(f"  {lap.id} [{lap.verdict}] {reason}")
    if exp.summary:
        print(f"summary: {exp.summary}")
    return 0


async def _cmd_frink_review(args: argparse.Namespace) -> int:
    from autopilot.domain.experiment import Experiment
    from autopilot.orchestrator.frink import _run_reviewer

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    exp = Experiment.load(_resolve_experiment_dir(project, args.exp_id))
    await _run_reviewer(exp, cfg, project)
    review = (exp._dir / "review.md") if exp._dir else None
    if review is None or not review.is_file():
        raise CLIError(reason="reviewer produced no review.md")
    print(f"wrote {review}")
    return 0


def _resolve_study_dir(project: Path, study_id: str | None) -> Path:
    root = project / ".dev" / "studies"
    if study_id:
        d = root / study_id
        if not (d / f"{study_id}.md").is_file():
            raise CLIError(reason=f"no study at {d}")
        return d
    candidates = sorted(d for d in root.glob("study-*") if (d / f"{d.name}.md").is_file())
    if not candidates:
        raise CLIError(reason=f"no studies under {root}")
    return candidates[-1]


async def _cmd_study_run(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.study import study_run

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    outcome = await study_run(project, cfg, Path(args.spec))
    st = outcome.study
    done = sum(1 for c in st.cells if c.status == "completed")
    print(f"{st.id} {st.status} cells={done}/{len(st.cells)} cost=${st.cost_usd:.2f}")
    return 0 if st.status == "completed" else 1


async def _cmd_study_status(args: argparse.Namespace) -> int:
    from autopilot.domain.study import Study

    project = _resolve_project_loose(args.project)
    st = Study.load(_resolve_study_dir(project, args.study_id))
    print(f"id: {st.id}")
    print(f"status: {st.status}")
    print(f"repetitions: {st.repetitions}")
    print(f"cost_usd: {st.cost_usd:.2f}")
    print(f"cells: {len(st.cells)}")
    for c in st.cells:
        params = ",".join(f"{k}={v}" for k, v in c.params.items())
        detail = c.error if c.status == "failed" else ""
        print(f"  {c.id} [{c.status}] {params} {detail or ''}".rstrip())
    if st.summary:
        print(f"summary: {st.summary}")
    return 0


async def _cmd_study_report(args: argparse.Namespace) -> int:
    from autopilot.domain.study import Study
    from autopilot.orchestrator.study import _run_analyst

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    st = Study.load(_resolve_study_dir(project, args.study_id))
    await _run_analyst(st, cfg, project)
    report = (st._dir / "report.md") if st._dir else None
    if report is None or not report.is_file():
        raise CLIError(reason="analyst produced no report.md")
    print(f"wrote {report}")
    return 0


# ---------- roadmap ----------


def _write_roadmap_blocks(
    project: Path, blocks: list[tuple[str, str]], *, allow_overwrite: bool
) -> list[Path]:
    """Write roadmap.md + goal-*.md blocks via Roadmap / Goal active-record _save().

    Per principle #4: entities own their persistence. The CLI parses agent text
    into entities, sets `_path`, and calls `_save()` — it does not write raw
    bytes. Re-serialisation via the entity's `_save` is intentional: the entity
    on disk is truth; agent text is transport.
    """
    from autopilot.domain.errors import ParseError, ValidationError
    from autopilot.domain.parse import parse_goal, parse_roadmap

    dev = project / ".dev"
    dev.mkdir(parents=True, exist_ok=True)
    goals_dir = dev / "goals"
    goals_dir.mkdir(parents=True, exist_ok=True)

    roadmap_block: tuple[str, str] | None = None
    goal_blocks: list[tuple[str, str]] = []
    for name, body in blocks:
        base = name.split("/")[-1]
        if base == "roadmap.md":
            roadmap_block = (base, body)
        elif base.startswith("goal-") and base.endswith(".md"):
            goal_blocks.append((base, body))
        else:
            raise CLIError(reason=f"unexpected file block in roadmap output: {name}")
    if roadmap_block is None:
        raise CLIError(reason="roadmap output missing `### FILE: roadmap.md` block")

    targets: list[tuple[Path, str]] = [(dev / "roadmap.md", roadmap_block[1])]
    for base, body in goal_blocks:
        targets.append((goals_dir / base, body))

    # Pre-flight overwrite check so a later parse failure can't leave half-written state.
    if not allow_overwrite:
        for path, _ in targets:
            if path.exists():
                raise CLIError(reason=f"refusing to overwrite existing file: {path}")

    written: list[Path] = []
    roadmap_path, roadmap_body = targets[0]
    try:
        roadmap = parse_roadmap(roadmap_body, path=roadmap_path)
    except (ParseError, ValidationError) as e:
        raise CLIError(reason=f"roadmap block failed to parse: {e}") from e
    roadmap._path = roadmap_path
    roadmap._save()
    written.append(roadmap_path)

    for path, body in targets[1:]:
        try:
            goal = parse_goal(body, path=path)
        except (ParseError, ValidationError) as e:
            raise CLIError(reason=f"roadmap block failed to parse: {e}") from e
        goal._path = path
        goal._save()
        written.append(path)
    return written


async def _cmd_roadmap_create(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_roadmap_prompt
    from autopilot.agents.runner import run_agent

    project = _resolve_project_loose(args.project)
    cfg = load_config(project_root=project)
    roadmap_path = project / ".dev" / "roadmap.md"
    if roadmap_path.is_file():
        raise CLIError(reason=f"roadmap already exists: {roadmap_path} (use `roadmap revise`)")

    research_text: str | None = None
    if args.research:
        rp = Path(args.research)
        if not rp.is_file():
            raise CLIError(reason=f"research file not found: {rp}")
        research_text = rp.read_text(encoding="utf-8")

    result = await run_agent(
        "roadmap",
        build_roadmap_prompt(project, research=research_text),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"roadmap call failed: {result.error or 'unknown error'}")
    blocks = _split_file_blocks(result.output)
    written = _write_roadmap_blocks(project, blocks, allow_overwrite=False)
    for p in written:
        print(f"wrote {p}")
    return 0


async def _cmd_roadmap_revise(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_roadmap_prompt
    from autopilot.agents.runner import run_agent

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    roadmap_path = project / ".dev" / "roadmap.md"
    existing = roadmap_path.read_text(encoding="utf-8")

    result = await run_agent(
        "roadmap",
        build_roadmap_prompt(project, existing_roadmap=existing),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"roadmap call failed: {result.error or 'unknown error'}")
    blocks = _split_file_blocks(result.output)
    written = _write_roadmap_blocks(project, blocks, allow_overwrite=True)
    for p in written:
        print(f"wrote {p}")
    return 0


# ---------- sprint plan / critique / judge ----------


def _latest_sprint_dir_or_error(project: Path) -> Path:
    from autopilot.orchestrator.execute import _latest_sprint_dir

    d = _latest_sprint_dir(project)
    if d is None:
        raise CLIError(reason="no sprints found")
    return d


async def _cmd_sprint_plan(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_planner_prompt
    from autopilot.agents.runner import run_agent
    from autopilot.domain.parse import parse_sprint
    from autopilot.domain.roadmap import Roadmap
    from autopilot.orchestrator.plan import (
        _load_analysis,
        _load_prior_sprints,
        _parse_planner_output,
        next_sprint_id,
    )

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    roadmap = Roadmap.load(project / ".dev" / "roadmap.md")
    if args.goal_id:
        goal = roadmap.goal(args.goal_id)
    else:
        goal = roadmap.next_pending_goal()
    if goal is None:
        raise CLIError(reason="no pending goal available to plan")

    prior_sprints = _load_prior_sprints(project)
    analysis = _load_analysis(project)
    sprint_id = next_sprint_id(project)
    sprint_dir = project / ".dev" / "sprints" / sprint_id

    result = await run_agent(
        "planner",
        build_planner_prompt(roadmap, goal, prior_sprints, analysis, None),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"planner call failed: {result.error or 'unknown error'}")

    sprint_text, task_texts = _parse_planner_output(result.output)
    sprint = parse_sprint(
        sprint_text,
        task_texts,
        expected_id=sprint_id,
        expected_primary_goal=goal.id,
    )
    sprint._dir = sprint_dir
    sprint_dir.mkdir(parents=True, exist_ok=True)
    sprint._save()
    for task in sprint.tasks:
        task._path = sprint_dir / f"task-{task.id}.md"
        task._save()
    print(f"{sprint.id} {sprint.status}")
    return 0


def _load_sprint_and_goal(project: Path, sprint_id: str | None) -> tuple[Any, Any, Any]:
    from autopilot.domain.roadmap import Roadmap
    from autopilot.domain.sprint import Sprint

    if sprint_id:
        sprint_dir = project / ".dev" / "sprints" / sprint_id
        if not sprint_dir.is_dir():
            raise CLIError(reason=f"sprint dir not found: {sprint_dir}")
    else:
        sprint_dir = _latest_sprint_dir_or_error(project)
    sprint = Sprint.load(sprint_dir)
    roadmap = Roadmap.load(project / ".dev" / "roadmap.md")
    goal = roadmap.goal(sprint.primary_goal)
    return sprint, goal, roadmap


async def _cmd_sprint_critique(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_critic_prompt
    from autopilot.agents.runner import run_agent
    from autopilot.domain.clock import now
    from autopilot.domain.sprint import RevisionRecord

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint, goal, _roadmap = _load_sprint_and_goal(project, args.sprint_id)

    result = await run_agent("critic", build_critic_prompt(sprint, goal), cfg, cwd=project)
    if not result.success:
        raise CLIError(reason=f"critic call failed: {result.error or 'unknown error'}")

    # Design choice: atomic critique writes a RevisionRecord with empty judge_verdict
    # — the judge atomic reads prior revision_rounds to decide how to proceed.
    # Append via direct mutation + _save; introducing a `record_critique` helper
    # would be a 1-call-site abstraction (YAGNI per principle 9).
    sprint.revision_rounds.append(
        RevisionRecord(
            critic_notes=result.output,
            judge_verdict="",
            feedback="",
            timestamp=now(),
        )
    )
    sprint._save()
    print(f"{sprint.id} critique: {len(sprint.revision_rounds)} round(s)")
    return 0


async def _cmd_sprint_judge(args: argparse.Namespace) -> int:
    from autopilot.agents.prompts import build_critic_prompt, build_judge_prompt
    from autopilot.agents.runner import run_agent
    from autopilot.domain.clock import now
    from autopilot.domain.parse import parse_verdict
    from autopilot.domain.sprint import RevisionRecord

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint, goal, _roadmap = _load_sprint_and_goal(project, args.sprint_id)

    # Design choice: if no prior critique has been recorded, call critic inline
    # so the judge has something to work with. Alternative would be to error out,
    # but that makes the command fragile in ad-hoc use; the behaviour mirrors
    # sprint_prepare which always runs critic before judge.
    critic_notes = ""
    if sprint.revision_rounds and sprint.revision_rounds[-1].critic_notes:
        critic_notes = sprint.revision_rounds[-1].critic_notes
    else:
        critic_result = await run_agent(
            "critic", build_critic_prompt(sprint, goal), cfg, cwd=project
        )
        critic_notes = (
            critic_result.output
            if critic_result.success
            else f"critic call failed: {critic_result.error}"
        )

    judge_result = await run_agent(
        "judge", build_judge_prompt(sprint, goal, critic_notes), cfg, cwd=project
    )
    if not judge_result.success:
        raise CLIError(reason=f"judge call failed: {judge_result.error or 'unknown error'}")
    verdict = parse_verdict(judge_result.output)

    sprint.revision_rounds.append(
        RevisionRecord(
            critic_notes=critic_notes,
            judge_verdict="READY" if verdict.ready else "NOT_READY",
            feedback=verdict.feedback,
            timestamp=now(),
        )
    )
    sprint._save()

    # Side effect per workflows §4.2: when judge says READY on a planning sprint,
    # approve it — mirrors sprint_prepare's behaviour exactly.
    if verdict.ready and sprint.status == "planning":
        sprint.approve()
        # Also mark the goal in-progress, matching sprint_prepare.
        goal.mark_in_progress(sprint.id)

    print(f"{sprint.id} judge: {'READY' if verdict.ready else 'NOT_READY'} status={sprint.status}")
    return 0 if verdict.ready else 1


# ---------- task ----------


def _resolve_task_and_sprint(task_file: str) -> tuple[Any, Any, Path]:
    from autopilot.domain.sprint import Sprint
    from autopilot.domain.task import Task

    path = Path(task_file).resolve()
    if not path.is_file():
        raise CLIError(reason=f"task file not found: {path}")
    task = Task.load(path)
    sprint_dir = path.parent
    sprint = Sprint.load(sprint_dir)
    # Swap in the just-loaded task so mutations on `task` propagate correctly.
    for i, t in enumerate(sprint.tasks):
        if t.id == task.id:
            sprint.tasks[i] = task
            break
    # Project root: parent of `.dev/sprints/`.
    sprints_parent = sprint_dir.parent
    if sprints_parent.name != "sprints":
        raise CLIError(reason=f"task file not under a `.dev/sprints/sprint-*/` layout: {path}")
    dev_dir = sprints_parent.parent
    if dev_dir.name != ".dev":
        raise CLIError(reason=f"unexpected layout (no .dev/ ancestor): {path}")
    project = dev_dir.parent
    return task, sprint, project


async def _cmd_task_run(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.execute import run_task

    task, sprint, project = _resolve_task_and_sprint(args.task_file)
    cfg = load_config(project_root=project)
    await run_task(task, sprint, cfg, project)
    print(f"{task.id} {task.status}")
    return 0 if task.status == "completed" else 1


async def _cmd_task_retry(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.execute import run_task

    task, sprint, project = _resolve_task_and_sprint(args.task_file)
    if task.status != "failed":
        raise CLIError(reason=f"task retry requires status=failed, got status={task.status}")
    cfg = load_config(project_root=project)
    # Task state machine (workflows §1.1): `failed → start → active`. run_task
    # calls task.start() which handles this transition.
    await run_task(task, sprint, cfg, project)
    print(f"{task.id} {task.status}")
    return 0 if task.status == "completed" else 1


# ---------- eval ----------


def _resolve_ref_entity(project: Path, ref) -> Any:
    """Load the entity pointed to by a parsed ref."""
    from autopilot.domain.roadmap import Roadmap
    from autopilot.domain.sprint import Sprint

    if ref.entity_type == "roadmap":
        return Roadmap.load(project / ".dev" / "roadmap.md")
    if ref.entity_type == "goal":
        roadmap = Roadmap.load(project / ".dev" / "roadmap.md")
        return roadmap.goal(ref.entity_id)
    if ref.entity_type == "sprint":
        sprint_dir = project / ".dev" / "sprints" / ref.entity_id
        if not sprint_dir.is_dir():
            raise CLIError(reason=f"sprint dir not found: {sprint_dir}")
        return Sprint.load(sprint_dir)
    if ref.entity_type == "task":
        sprint_id, task_id = ref.entity_id.split("/", 1)
        sprint_dir = project / ".dev" / "sprints" / sprint_id
        if not sprint_dir.is_dir():
            raise CLIError(reason=f"sprint dir not found: {sprint_dir}")
        sprint = Sprint.load(sprint_dir)
        for t in sprint.tasks:
            if t.id == task_id:
                return t
        raise CLIError(reason=f"task {task_id} not found in {sprint_id}")
    raise CLIError(reason=f"unknown entity type: {ref.entity_type}")


def _entity_evals(entity: Any) -> list:
    return list(getattr(entity, "eval", []) or [])


def _entity_id_for(entity: Any) -> str:
    """The entity id string to embed in an EvalRef."""
    from autopilot.domain.roadmap import Roadmap

    if isinstance(entity, Roadmap):
        return "roadmap"
    return getattr(entity, "id", "unknown")


def _context_payload_plain(payload: dict) -> dict:
    """Strip non-YAML-serialisable objects for `eval show`."""
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, Path):
            out[k] = str(v)
        elif isinstance(v, AutopilotConfig):
            # Don't dump the whole config; just note its presence.
            out[k] = "<AutopilotConfig>"
        else:
            try:
                yaml.safe_dump(v)
                out[k] = v
            except Exception:  # noqa: BLE001
                out[k] = repr(v)
    return out


async def _cmd_eval_show(args: argparse.Namespace) -> int:
    from autopilot.domain.ids import EvalRef, parse_ref
    from autopilot.orchestrator.evaluate import build_eval_context

    ref = parse_ref(args.ref)
    if ref.eval_index is None:
        raise CLIError(reason=f"`eval show` requires `#<i>`: {args.ref}")

    project = _resolve_project(None)
    cfg = load_config(project_root=project)
    entity = _resolve_ref_entity(project, ref)
    evals = _entity_evals(entity)
    if ref.eval_index >= len(evals):
        raise CLIError(
            reason=f"eval index {ref.eval_index} out of range ({len(evals)} evals on entity)"
        )
    eval_def = evals[ref.eval_index]
    eval_ref = EvalRef(
        entity_type=ref.entity_type,
        entity_id=_entity_id_for(entity),
        eval_index=ref.eval_index,
    )
    ctx = build_eval_context(eval_ref, entity, project_root=project, cfg=cfg)
    dump = {
        "ref": args.ref,
        "eval": eval_def.to_dict(),
        "payload": _context_payload_plain(ctx.payload),
    }
    print(yaml.safe_dump(dump, sort_keys=False).rstrip())
    return 0


async def _cmd_eval_run(args: argparse.Namespace) -> int:
    from autopilot.domain.eval import run_eval
    from autopilot.domain.ids import EvalRef, parse_ref
    from autopilot.orchestrator.evaluate import build_eval_context

    ref = parse_ref(args.ref)
    project = _resolve_project(None)
    cfg = load_config(project_root=project)
    entity = _resolve_ref_entity(project, ref)
    evals = _entity_evals(entity)
    if not evals:
        raise CLIError(reason=f"no evals on entity: {args.ref}")

    if ref.eval_index is None:
        indices = list(range(len(evals)))
    else:
        if ref.eval_index >= len(evals):
            raise CLIError(
                reason=(f"eval index {ref.eval_index} out of range ({len(evals)} evals on entity)")
            )
        indices = [ref.eval_index]

    any_failed = False
    for idx in indices:
        eval_ref = EvalRef(
            entity_type=ref.entity_type,
            entity_id=_entity_id_for(entity),
            eval_index=idx,
        )
        ctx = build_eval_context(eval_ref, entity, project_root=project, cfg=cfg)
        run = await run_eval(evals[idx], eval_ref, ctx)
        print(f"{run.id} {run.status}")
        if run.status != "passed":
            any_failed = True
    return 0 if not any_failed else 1


# ---------- dispatch ----------


async def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.cmd
    sub = getattr(args, "subcmd", None)
    match (cmd, sub):
        case ("ralph", _):
            return await _cmd_ralph(args)
        case ("analyse", _):
            return await _cmd_analyse(args)
        case ("lisa", _):
            return await _cmd_lisa(args)
        case ("roadmap", "create"):
            return await _cmd_roadmap_create(args)
        case ("roadmap", "revise"):
            return await _cmd_roadmap_revise(args)
        case ("sprint", "plan"):
            return await _cmd_sprint_plan(args)
        case ("sprint", "critique"):
            return await _cmd_sprint_critique(args)
        case ("sprint", "judge"):
            return await _cmd_sprint_judge(args)
        case ("sprint", "evaluate"):
            return await _cmd_sprint_evaluate(args)
        case ("sprint", "prepare"):
            return await _cmd_sprint_prepare(args)
        case ("sprint", "execute"):
            return await _cmd_sprint_execute(args)
        case ("task", "run"):
            return await _cmd_task_run(args)
        case ("task", "retry"):
            return await _cmd_task_retry(args)
        case ("frink", "start"):
            return await _cmd_frink_start(args)
        case ("frink", "status"):
            return await _cmd_frink_status(args)
        case ("frink", "review"):
            return await _cmd_frink_review(args)
        case ("study", "run"):
            return await _cmd_study_run(args)
        case ("study", "status"):
            return await _cmd_study_status(args)
        case ("study", "report"):
            return await _cmd_study_report(args)
        case ("eval", "show"):
            return await _cmd_eval_show(args)
        case ("eval", "run"):
            return await _cmd_eval_run(args)
        case _:
            raise CLIError(reason=f"unknown command: {cmd} {sub}".strip())


_NESTED_CLAUDE_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def _scrub_nested_claude_env() -> None:
    """Drop env vars that make Agent-SDK children refuse to launch under a Claude
    Code parent. Autopilot itself never reads them; the Agent SDK subprocess
    inherits os.environ, and these vars trigger `Claude Code cannot be launched
    inside another Claude Code session` in the child. Idempotent no-op if absent.
    """
    for name in _NESTED_CLAUDE_ENV_VARS:
        os.environ.pop(name, None)


def main(argv: list[str] | None = None) -> int:
    _scrub_nested_claude_env()
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_id = uuid.uuid4().hex[:12]
    os.environ.setdefault("AUTOPILOT_RUN_ID", run_id)

    if args.verbose:
        os.environ["AUTOPILOT_VERBOSE"] = "1"

    emit("run.start", cmd=args.cmd, subcmd=getattr(args, "subcmd", None))
    try:
        code = asyncio.run(_dispatch(args))
    except CLIError as e:
        print(str(e), file=sys.stderr)
        emit("run.end", status="cli_error", message=str(e))
        return 2
    except Exception as e:  # noqa: BLE001 — top-level CLI guard
        print(f"error: {e}", file=sys.stderr)
        emit("run.end", status="error", message=str(e), error_type=type(e).__name__)
        return 1
    emit("run.end", status="ok", exit_code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
