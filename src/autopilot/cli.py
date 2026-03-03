"""CLI entry point for autopilot."""

import argparse
import asyncio
import importlib.resources
import sys
from pathlib import Path

from .log import log, log_header
from .manifest import MANIFEST_PATH, discover_projects, get_task_summary, load_manifest
from .orchestrator import process_project


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
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing agents",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    agents_dir = args.agents_dir or _default_agents_dir()

    project_paths: list[Path] = []

    if args.scan:
        project_paths = discover_projects(args.scan.expanduser().resolve())
        if not project_paths:
            print(f"  No projects with {MANIFEST_PATH} found under {args.scan}")
            sys.exit(0)
    elif args.projects:
        project_paths = [Path(p).expanduser().resolve() for p in args.projects]
    else:
        cwd = Path.cwd()
        if (cwd / ".dev" / "autopilot.md").exists():
            project_paths = [cwd]
        else:
            print(f"  No {MANIFEST_PATH} in current directory. Provide paths or use --scan.")
            sys.exit(1)

    log_header(f"Autopilot — {len(project_paths)} project(s)")

    if args.dry_run:
        print("  [DRY RUN MODE — no agents will be executed]\n")
        for path in project_paths:
            manifest = load_manifest(path)
            if manifest:
                status = "approved" if manifest.approved else "needs review"
                print(f"  {path.name}: {manifest.name} — {status} — {get_task_summary(manifest)}")
            else:
                print(f"  {path.name}: no manifest")
        return

    for project_path in project_paths:
        if not project_path.is_dir():
            log(str(project_path), "Not a directory — skipping", "⏭️")
            continue
        await process_project(project_path, agents_dir)

    log_header("Autopilot — complete")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
