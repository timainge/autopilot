"""CLI entry point for autopilot."""

import argparse
import asyncio
import importlib.metadata
import importlib.resources
import os
import sys
from pathlib import Path

from .config import load_config
from .log import log, log_header
from .manifest import (
    MANIFEST_PATH,
    detect_git_user,
    discover_all_projects,
    discover_projects,
    get_repo_owner,
    get_task_summary,
    load_manifest,
    reset_stuck_project,
)
from .orchestrator import (
    build_portfolio,
    plan_project,
    process_project,
    research_project,
    roadmap_project,
    strategize_project,
)

SUBCOMMANDS = {"run", "plan", "research", "roadmap", "portfolio", "strategize"}
_VALUE_FLAGS = {"--scan", "--agents-dir", "--context"}  # flags that consume next arg
_TERMINAL_FLAGS = {"--version", "--help", "-h"}  # let top-level parser handle these


def _inject_default_subcommand() -> None:
    """Inject 'run' as the default subcommand if none is present."""
    raw = sys.argv[1:]
    if raw and raw[0] in _TERMINAL_FLAGS:
        return  # don't inject — top-level parser handles --version/--help
    skip_next = False
    for arg in raw:
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_FLAGS:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        if arg in SUBCOMMANDS:
            return  # subcommand already present
        else:
            break  # first positional is a path, not a subcommand
    sys.argv.insert(1, "run")


def _default_agents_dir() -> Path:
    """Resolve the bundled agents directory using importlib.resources."""
    return Path(str(importlib.resources.files("autopilot") / "agents"))


def _add_common(p: argparse.ArgumentParser) -> None:
    """Add shared arguments to a subparser."""
    p.add_argument("projects", nargs="*", help="Project directories to process")
    p.add_argument("--scan", type=Path, help="Scan a directory for projects")
    p.add_argument(
        "--agents-dir",
        type=Path,
        default=None,
        help="Directory containing agent role configs (default: bundled agents)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing agents",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Autonomous project session orchestrator for Claude Code",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {importlib.metadata.version('claude-autopilot')}",
    )

    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.required = True

    # run subcommand
    run_p = subparsers.add_parser("run", help="Execute pending tasks for projects")
    _add_common(run_p)
    run_p.add_argument(
        "--resume",
        action="store_true",
        help="Reset stuck projects and retry failed tasks",
    )
    run_p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve the manifest if the judge deems it ready",
    )

    # plan subcommand
    plan_p = subparsers.add_parser(
        "plan", help="Run the planner agent to create or improve project manifests"
    )
    _add_common(plan_p)
    plan_p.add_argument(
        "--context",
        type=Path,
        default=None,
        help="File to use as additional context for planning (e.g. existing TODO list)",
    )
    plan_p.add_argument(
        "--review",
        action="store_true",
        help="Run a critic agent after planning to verify and improve the plan",
    )

    # research subcommand
    research_p = subparsers.add_parser(
        "research", help="Run the researcher agent to analyze projects"
    )
    _add_common(research_p)
    research_p.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="Include all projects (don't skip forks/clones)",
    )

    # roadmap subcommand
    roadmap_p = subparsers.add_parser("roadmap", help="Build a shipping roadmap for each project")
    _add_common(roadmap_p)
    roadmap_p.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="Include all projects (don't skip forks/clones)",
    )

    # portfolio subcommand
    portfolio_p = subparsers.add_parser(
        "portfolio", help="Build a portfolio overview of all scanned projects"
    )
    _add_common(portfolio_p)
    portfolio_p.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="Include all projects (don't skip forks/clones)",
    )

    strategize_p = subparsers.add_parser(
        "strategize", help="Run the strategist agent to create a strategy manifest"
    )
    _add_common(strategize_p)
    strategize_p.add_argument(
        "--context",
        type=Path,
        default=None,
        help="File to use as the primary goal/context (e.g. a thought bubble)",
    )
    strategize_p.add_argument(
        "--deep",
        action="store_true",
        help="Run deep research before strategizing (Sprint 4 — not yet implemented)",
    )

    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    agents_dir = args.agents_dir or _default_agents_dir()

    # Load global config (no project path) and apply env/flag defaults
    global_cfg = load_config()

    if args.scan is None and global_cfg.scan_root:
        args.scan = Path(global_cfg.scan_root).expanduser()

    if global_cfg.git_user and not os.environ.get("AUTOPILOT_GIT_USER"):
        os.environ["AUTOPILOT_GIT_USER"] = global_cfg.git_user

    project_paths: list[Path] = []

    broad = args.subcommand in {"plan", "research", "roadmap", "portfolio", "strategize"}

    if args.subcommand == "portfolio" and not args.scan and not args.projects:
        print("  portfolio requires --scan or explicit project paths.")
        sys.exit(1)

    if args.scan:
        scan_root = args.scan.expanduser().resolve()
        if broad:
            project_paths = discover_all_projects(scan_root)
            if not project_paths:
                print(f"  No project directories found under {args.scan}")
                sys.exit(0)
        else:
            project_paths = discover_projects(scan_root, cfg=global_cfg)
            if not project_paths:
                print(f"  No projects with {MANIFEST_PATH} found under {args.scan}")
                sys.exit(0)
    elif args.projects:
        project_paths = [Path(p).expanduser().resolve() for p in args.projects]
    else:
        cwd = Path.cwd()
        if args.subcommand in {"research", "plan", "roadmap", "strategize"}:
            project_paths = [cwd]
        elif global_cfg.manifest_path(cwd).exists():
            project_paths = [cwd]
        else:
            print(f"  No {MANIFEST_PATH} in current directory. Provide paths or use --scan.")
            sys.exit(1)

    # Filter non-owned repos in broad scan mode (unless --all)
    skipped: list[tuple[Path, str]] = []
    if broad and args.scan and not getattr(args, "include_all", False):
        git_user = detect_git_user()
        if git_user:
            owned: list[Path] = []
            for p in project_paths:
                owner = get_repo_owner(p)
                if owner is None or owner.lower() == git_user.lower():
                    owned.append(p)
                else:
                    skipped.append((p, owner))
            project_paths = owned
        else:
            print(
                "  ⚠️  Git user not detected — including all projects.\n"
                "     To filter forks, set one of:\n"
                "       export AUTOPILOT_GIT_USER=<username>\n"
                "       git config --global autopilot.user <username>\n"
            )

    mode_label = "Autopilot" if args.subcommand == "run" else args.subcommand.capitalize()
    log_header(f"{mode_label} — {len(project_paths)} project(s)")

    if skipped:
        print(f"  Skipped {len(skipped)} non-owned repo(s) (use --all to include):")
        for p, owner in skipped:
            print(f"    {p.name} (owner: {owner})")
        print()

    if args.dry_run:
        dry_label = mode_label.lower()
        print(f"  [DRY RUN MODE — no agents will be executed ({dry_label})]\n")
        for path in project_paths:
            if broad:
                has_summary = (path / ".dev" / "project-summary.md").exists()
                tag = "has summary" if has_summary else "no summary"
                print(f"  {path.name}: would {dry_label} ({tag})")
            else:
                manifest = load_manifest(path)
                if manifest:
                    status = "approved" if manifest.approved else "needs review"
                    print(
                        f"  {path.name}: {manifest.name} — {status} — {get_task_summary(manifest)}"
                    )
                else:
                    print(f"  {path.name}: no manifest")
        return

    if args.subcommand == "portfolio":
        scan_root = args.scan.expanduser().resolve() if args.scan else project_paths[0].parent
        await build_portfolio(scan_root, project_paths, agents_dir, cfg=global_cfg)
    else:
        context_file = getattr(args, "context", None)
        if context_file:
            context_file = context_file.expanduser().resolve()
        for project_path in project_paths:
            if not project_path.is_dir():
                log(str(project_path), "Not a directory — skipping", "⏭️")
                continue
            cfg = load_config(project_path)
            match args.subcommand:
                case "plan":
                    await plan_project(
                        project_path, agents_dir, context_file, review=args.review, cfg=cfg
                    )
                case "research":
                    await research_project(project_path, agents_dir, cfg=cfg)
                case "roadmap":
                    await roadmap_project(project_path, agents_dir, cfg=cfg)
                case "strategize":
                    await strategize_project(
                        project_path, agents_dir, context_file, deep=args.deep, cfg=cfg
                    )
                case "run":
                    if args.resume:
                        if reset_stuck_project(project_path):
                            log(
                                str(project_path.name),
                                "Reset stuck project — retrying failed tasks",
                                "🔄",
                            )
                        else:
                            log(
                                str(project_path.name),
                                "Project is not stuck — proceeding normally",
                                "ℹ️",
                            )
                    await process_project(
                        project_path, agents_dir, auto_approve=args.auto_approve, cfg=cfg
                    )

    log_header(f"{mode_label} — complete")


def main() -> None:
    _inject_default_subcommand()
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
