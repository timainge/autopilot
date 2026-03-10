# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Autopilot is an autonomous project session orchestrator for Claude Code. It reads project manifests (`.dev/autopilot.md`), evaluates readiness via an LLM judge, and executes tasks sequentially through the Anthropic Agent SDK. It automates the outer loop of hobby project development — you write the plan, autopilot runs it.

## Architecture

Single Python package at `src/autopilot/`. Key modules:

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Argparse CLI, project discovery, fork-filtering, async entry point |
| `orchestrator.py` | All agent pipelines: judge/worker/planner/researcher/portfolio/roadmap |
| `manifest.py` | Parse/load/write manifests, task dependency resolution, agent config loading, git helpers |
| `prompts.py` | Prompt builders for all agent roles; judge verdict parsing |
| `agent.py` | Thin wrapper around `claude_agent_sdk.query()` — streams messages, tracks cost, names sessions |
| `models.py` | Dataclasses: `Task`, `Manifest`, `AgentConfig`, `AgentResult` |
| `log.py` | Timestamped status logging |

**Agent role configs** live in `src/autopilot/agents/*.md` — markdown files with YAML frontmatter defining system prompts, allowed tools, budget, and permission mode for each role: `judge`, `worker`, `planner`, `critic`, `researcher`, `portfolio`, `roadmap`.

## Core Pipeline

**Normal run** (`orchestrator.py`): two-phase flow per project:
1. **Judge phase** — if `approved: false`, runs the judge agent. Human must set `approved: true` (or pass `--auto-approve`).
2. **Worker phase** — if `approved: true`, loops through pending tasks sequentially. Each task: spawn worker agent → verify marked done → retry on failure up to `max_task_attempts`.

**`--plan`**: Lazily runs researcher + roadmap agents if `.dev/project-summary.md` / `.dev/roadmap.md` don't exist, then runs the planner agent to write `.dev/autopilot.md`. Pass `--context <file>` to skip lazy research and seed the planner directly. Pass `--review` to run the critic agent afterwards.

**`--research`**: Runs researcher agent → writes `.dev/project-summary.md`. Incremental: re-running compares stored commit hash against current state, does full or partial re-analysis as needed.

**`--roadmap`**: Runs roadmap agent → writes `.dev/roadmap.md`. Uses research summary if available.

**`--portfolio`**: Runs portfolio agent across all discovered projects → writes `<scan_dir>/.dev/portfolio.md`. Requires `--scan` or explicit paths.

## Key Patterns

- **Manifest format**: YAML frontmatter + markdown checkboxes at `.dev/autopilot.md`. Task metadata persisted inline: `[id: foo]`, `[depends: bar]`, `[attempts: 2]`, `[status: failed]`, `[error: ...]`.
- **Session naming**: Every `run_agent()` call sets `extra_args={"session-name": "autopilot/{project}/{role}"}` so sessions appear distinctively in Claude Code's `/resume` history.
- **Project discovery**: `discover_projects()` finds dirs with `.dev/autopilot.md`; `discover_all_projects()` finds any project-like dir (git, package.json, pyproject.toml, etc.).
- **Fork filtering**: In scan mode, non-owned repos are skipped by comparing git remote owner to detected user (`AUTOPILOT_GIT_USER` env → `git config autopilot.user` → `gh api user`). Use `--all` to disable.
- **Default cwd**: When no path arg is provided, autopilot defaults to the current directory for all modes.

## .dev Convention

All autopilot working files within a project live under `.dev/` (which should be in `.gitignore`):
- `.dev/autopilot.md` — project manifest
- `.dev/project-summary.md` — researcher agent output
- `.dev/roadmap.md` — roadmap agent output
- `<scan_dir>/.dev/portfolio.md` — portfolio agent output

## Development Commands

```bash
uv pip install -e .          # Install (editable)
autopilot .                  # Run on current directory
autopilot --plan .           # Generate/improve manifest (lazy research first)
autopilot --research .       # Analyse project
autopilot --roadmap .        # Build shipping roadmap
autopilot --scan ~/Projects  # Auto-discover and process all projects
ruff check src/              # Lint
ruff format --check src/     # Format check
```

There are no tests yet (smoke tests planned before v0.1.0 release — see `.dev/plans/01-naming.md`).

## Code Style

- Python 3.11+, async/await throughout
- Ruff linter: line length 100, rules `E, F, I, N, W, UP`
- Dataclasses (not Pydantic)
- Type hints with `X | None` union syntax (not `Optional`)

## Documentation

When adding or changing features that affect CLI usage, agent roles, or the manifest format, update `README.md`. The README is the primary user-facing documentation.

Release plans and post-MVP features tracked in `.dev/roadmap.md` and `.dev/plans/`.
