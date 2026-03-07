"""CLI entry point for autopilot."""

import argparse
import asyncio
import importlib.resources
import sys
from pathlib import Path

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
from .orchestrator import build_portfolio, plan_project, process_project, research_project


def _default_agents_dir() -> Path:
    """Resolve the bundled agents directory using importlib.resources."""
    return Path(str(importlib.resources.files("autopilot") / "agents"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Autonomous project session orchestrator for Claude Code",
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project directories to process",
    )
    parser.add_argument(
        "--scan",
        type=Path,
        help="Scan a directory for projects containing .dev/autopilot.md",
    )
    parser.add_argument(
        "--agents-dir",
        type=Path,
        default=None,
        help="Directory containing agent role configs (default: bundled agents)",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Run the planner agent to create or improve project manifests",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=None,
        help="File to use as additional context for planning (e.g. existing TODO list)",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Run the researcher agent to analyze projects instead of processing tasks",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="Build a portfolio overview of all scanned projects",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all projects in research/portfolio mode (don't skip forks/clones)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reset stuck projects and retry failed tasks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing agents",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    agents_dir = args.agents_dir or _default_agents_dir()

    project_paths: list[Path] = []

    broad_mode = args.research or args.portfolio or args.plan

    if args.portfolio and not args.scan and not args.projects:
        print("  --portfolio requires --scan or explicit project paths.")
        sys.exit(1)

    if args.scan:
        scan_root = args.scan.expanduser().resolve()
        if broad_mode:
            project_paths = discover_all_projects(scan_root)
            if not project_paths:
                print(f"  No project directories found under {args.scan}")
                sys.exit(0)
        else:
            project_paths = discover_projects(scan_root)
            if not project_paths:
                print(f"  No projects with {MANIFEST_PATH} found under {args.scan}")
                sys.exit(0)
    elif args.projects:
        project_paths = [Path(p).expanduser().resolve() for p in args.projects]
    else:
        cwd = Path.cwd()
        if args.research or args.plan:
            project_paths = [cwd]
        elif (cwd / ".dev" / "autopilot.md").exists():
            project_paths = [cwd]
        else:
            print(f"  No {MANIFEST_PATH} in current directory. Provide paths or use --scan.")
            sys.exit(1)

    # Filter non-owned repos in research/portfolio scan mode (unless --all)
    skipped: list[tuple[Path, str]] = []
    if broad_mode and args.scan and not getattr(args, "all"):
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

    if args.portfolio:
        mode_label = "Portfolio"
    elif args.research:
        mode_label = "Research"
    elif args.plan:
        mode_label = "Plan"
    else:
        mode_label = "Autopilot"
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
            if broad_mode:
                has_summary = (path / ".dev" / "research" / "summary.md").exists()
                tag = "has summary" if has_summary else "no summary"
                print(f"  {path.name}: would {dry_label} ({tag})")
            else:
                manifest = load_manifest(path)
                if manifest:
                    status = "approved" if manifest.approved else "needs review"
                    print(
                        f"  {path.name}: {manifest.name}"
                        f" — {status} — {get_task_summary(manifest)}"
                    )
                else:
                    print(f"  {path.name}: no manifest")
        return

    if args.portfolio:
        scan_root = args.scan.expanduser().resolve() if args.scan else project_paths[0].parent
        await build_portfolio(scan_root, project_paths, agents_dir)
    else:
        context_file = args.context.expanduser().resolve() if args.context else None
        for project_path in project_paths:
            if not project_path.is_dir():
                log(str(project_path), "Not a directory — skipping", "⏭️")
                continue
            if args.plan:
                await plan_project(project_path, agents_dir, context_file)
            elif args.research:
                await research_project(project_path, agents_dir)
            else:
                if args.resume:
                    if reset_stuck_project(project_path):
                        log(str(project_path.name), "Reset stuck project — retrying failed tasks", "🔄")
                    else:
                        log(str(project_path.name), "Project is not stuck — proceeding normally", "ℹ️")
                await process_project(project_path, agents_dir)

    log_header(f"{mode_label} — complete")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
