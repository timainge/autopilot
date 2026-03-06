# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autopilot is an autonomous project session orchestrator. It reads project manifests (`.dev/autopilot.md`), evaluates readiness via an LLM judge agent, and executes tasks sequentially through Claude Code via the Anthropic Agent SDK. It automates the outer loop of hobby project development.

## .dev Convention

All autopilot working files within a project live under `.dev/`:
- `.dev/autopilot.md` — project manifest (tasks, config, plan)
- `.dev/research/summary.md` — researcher agent output
- `<scan_dir>/.dev/portfolio.md` — portfolio agent output
- Projects should add `.dev/` to their `.gitignore`

## Development Commands

```bash
# Install (editable)
uv pip install -e .

# Run
autopilot /path/to/project              # Process one project
autopilot --scan ~/Projects             # Auto-discover projects
autopilot --scan ~/Projects --dry-run   # Preview only
autopilot --plan /path/to/project       # Generate or improve a manifest
autopilot --plan --context TODO.md .    # Plan with a context file
autopilot --research /path/to/project   # Research a project
autopilot --research --scan ~/Projects  # Research all projects
autopilot --portfolio --scan ~/Projects # Portfolio overview
autopilot --agents-dir /path/to/agents  # Use custom agent configs
python -m autopilot                     # Alternative entry point

# Lint
ruff check src/
ruff format --check src/
```

There are no tests yet.

## Architecture

The codebase is a single Python package at `src/autopilot/`.

**Core pipeline** (`orchestrator.py`): Two-phase flow per project:
1. **Judge phase** — if `approved: false`, runs the judge agent to evaluate manifest readiness. Never auto-approves; human must set `approved: true`.
2. **Worker phase** — if `approved: true`, loops through pending tasks sequentially. Each task: spawn worker agent → verify task marked done → handle retries on failure.

**Plan mode** (`--plan`): Runs the planner agent to create or improve `.dev/autopilot.md`. Accepts an optional `--context` file (TODO list, spec, etc.) passed to `build_planner_prompt()`.

**Research mode** (`--research`): Runs the researcher agent on a project and writes findings to `.dev/research/summary.md`. Doesn't require a manifest — discovers projects by common markers (.git, package.json, pyproject.toml, etc.).

**Portfolio mode** (`--portfolio`): Runs the portfolio agent across all discovered projects and writes `<scan_dir>/.dev/portfolio.md`. Projects with existing research summaries are indexed from those; others get a quick assessment.

**Module responsibilities:**
- `cli.py` — argparse CLI, async entry point, project discovery, fork-filtering logic
- `orchestrator.py` — judge/worker/planner/researcher/portfolio pipeline, task execution loop, retry logic
- `manifest.py` — parse/load/write manifests (YAML frontmatter + markdown checkboxes), task dependency resolution, agent config loading, git user detection
- `prompts.py` — prompt builders for all five agent roles, judge verdict parsing
- `agent.py` — thin wrapper around `claude_agent_sdk.query()`, streams messages, tracks cost
- `models.py` — dataclasses: `Task`, `Manifest`, `AgentConfig`, `AgentResult`
- `log.py` — timestamped status logging

**Agent role configs** (`src/autopilot/agents/*.md`): Markdown files with YAML frontmatter defining system prompts, allowed tools, budget, and permission mode for each role: `judge`, `worker`, `planner`, `researcher`, `portfolio`.

## Key Patterns

- **Manifest format**: Markdown with YAML frontmatter at `.dev/autopilot.md`. Tasks are markdown checkboxes with inline metadata like `[id: foo]`, `[depends: bar]`, `[attempts: 2]`, `[status: failed]`, `[error: ...]`.
- **Task IDs**: Auto-slugified from title (`slugify()` in `manifest.py`) unless overridden with `[id: ...]`.
- **Task persistence**: Status, error, and attempt count are persisted as inline bracket notation in the manifest file, not just in memory. This survives reloads. The `Task.last_error` field holds the last failure message for retry context.
- **Agent execution**: Each `run_agent()` call spawns a fresh Claude Code session via the SDK's `query()` async generator. Cost is tracked per invocation. `setting_sources = ["project"]` means it picks up any `.claude/` config present in the project directory.
- **Dependency resolution**: `get_next_task()` finds the first pending task whose dependencies are all done and whose attempt count hasn't hit `max_task_attempts`.
- **Project discovery**: `discover_projects()` finds directories with `.dev/autopilot.md` (used for normal mode). `discover_all_projects()` finds any directory with common project markers (used for research/portfolio broad mode).
- **Fork filtering**: In research/portfolio scan mode, non-owned repos are skipped by comparing the git remote owner against the detected git user (`AUTOPILOT_GIT_USER` env var → `git config autopilot.user` → `gh api user`). Use `--all` to disable.

## Documentation

When adding or changing features that affect CLI usage, agent roles, or the manifest format, update `README.md` to match. The README is the primary user-facing documentation.

## Code Style

- Python 3.11+, async/await throughout
- Ruff linter: line length 100, rules `E, F, I, N, W, UP`
- Dataclasses (not Pydantic)
- Type hints with `X | None` union syntax (not `Optional`)
