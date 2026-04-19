"""Autopilot CLI entry point. Per workflows §6."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from autopilot.config import load_config
from autopilot.domain.errors import CLIError
from autopilot.log import emit


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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autopilot", description="Autopilot CLI")
    p.add_argument("--verbose", action="store_true", help="emit JSONL log lines to stderr")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _proj(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("project", nargs="?", default=None)

    sp = sub.add_parser("smithers", help="plan a new sprint")
    _proj(sp)
    sp.add_argument("--goal", dest="goal_id", default=None)

    sp = sub.add_parser("homer", help="execute a sprint")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)

    sp = sub.add_parser("ralph", help="plan/execute/evaluate until goals met")
    _proj(sp)

    sp = sub.add_parser("research", help="research a topic (stub)")
    _proj(sp)
    sp.add_argument("--topic", default=None)

    roadmap = sub.add_parser("roadmap", help="roadmap operations")
    roadmap_sub = roadmap.add_subparsers(dest="subcmd", required=True)
    sp = roadmap_sub.add_parser("create")
    _proj(sp)
    sp.add_argument("--research", default=None)
    sp = roadmap_sub.add_parser("revise")
    _proj(sp)

    sprint = sub.add_parser("sprint", help="sprint sub-commands")
    sprint_sub = sprint.add_subparsers(dest="subcmd", required=True)
    sp = sprint_sub.add_parser("plan")
    _proj(sp)
    sp.add_argument("--goal", dest="goal_id", default=None)
    sp = sprint_sub.add_parser("critique")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("judge")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("evaluate")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)
    sp = sprint_sub.add_parser("execute")
    _proj(sp)
    sp.add_argument("--sprint", dest="sprint_id", default=None)

    task = sub.add_parser("task", help="task operations")
    task_sub = task.add_subparsers(dest="subcmd", required=True)
    sp = task_sub.add_parser("run")
    sp.add_argument("task_file")
    sp = task_sub.add_parser("retry")
    sp.add_argument("task_file")

    eval_ = sub.add_parser("eval", help="eval operations")
    eval_sub = eval_.add_subparsers(dest="subcmd", required=True)
    sp = eval_sub.add_parser("show")
    sp.add_argument("ref")
    sp = eval_sub.add_parser("run")
    sp.add_argument("ref")

    return p


async def _cmd_smithers(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.plan import smithers

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint = await smithers(project, cfg, goal_id=args.goal_id)
    print(f"{sprint.id} {sprint.status}")
    return 0 if sprint.status == "approved" else 1


async def _cmd_homer(args: argparse.Namespace) -> int:
    from autopilot.orchestrator.execute import homer

    project = _resolve_project(args.project)
    cfg = load_config(project_root=project)
    sprint = await homer(project, cfg, sprint_id=args.sprint_id)
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
    verdict = await sprint_evaluate(sprint, goal, roadmap, cfg, project)
    print(f"achieved={verdict.achieved}: {verdict.summary}")
    return 0 if verdict.achieved else 1


def _stub(cmd: str) -> int:
    print(
        f"`autopilot {cmd}` is not implemented in Phase 1. "
        f"Use `autopilot smithers | homer | ralph | sprint evaluate` instead.",
        file=sys.stderr,
    )
    return 2


async def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.cmd
    sub = getattr(args, "subcmd", None)
    if cmd == "smithers":
        return await _cmd_smithers(args)
    if cmd == "homer":
        return await _cmd_homer(args)
    if cmd == "ralph":
        return await _cmd_ralph(args)
    if cmd == "sprint" and sub == "execute":
        return await _cmd_homer(args)
    if cmd == "sprint" and sub == "evaluate":
        return await _cmd_sprint_evaluate(args)
    # All other atomic commands are Phase-1 stubs — argparse dispatch exists so
    # --help is complete and future phases can wire them up.
    return _stub(f"{cmd} {sub}" if sub else cmd)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_id = uuid.uuid4().hex[:12]
    os.environ.setdefault("AUTOPILOT_RUN_ID", run_id)

    if args.verbose:
        # Minimal verbose path: log events also go to stderr via a mirrored emit.
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
