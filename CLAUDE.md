# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Autopilot is an autonomous project session orchestrator for Claude Code. It reads project manifests (`.dev/sprint.md`), evaluates readiness via an LLM judge, and executes tasks sequentially through the Anthropic Agent SDK. It automates the outer loop of hobby project development — you write the plan, autopilot runs it.

## Architecture

Single Python package at `src/autopilot/`. Key modules:

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Argparse CLI, project discovery, fork-filtering, async entry point |
| `orchestrator.py` | All agent pipelines: judge/worker/planner/researcher/portfolio/roadmap/sprint |
| `manifest.py` | Parse/load/write manifests, task dependency resolution, agent config loading, runbook I/O, sprint log I/O |
| `prompts.py` | Prompt builders for all agent roles; judge verdict parsing |
| `agent.py` | Thin wrapper around `claude_agent_sdk.query()` — streams messages, tracks cost, names sessions |
| `models.py` | Dataclasses: `Task`, `Manifest`, `AgentConfig`, `AgentResult`, `SprintResult` |
| `config.py` | `AutopilotConfig` dataclass with v2 fields; `load_config()` from TOML |
| `log.py` | Timestamped status logging |

**Agent role configs** live in `src/autopilot/agents/*.md` — markdown files with YAML frontmatter defining system prompts, allowed tools, budget, and permission mode for each role: `judge`, `worker`, `planner`, `critic`, `researcher`, `portfolio`, `roadmap`, `deep-researcher`.

**Bundled runbooks** live in `src/autopilot/runbooks/*.md` — markdown reference docs loaded at runtime via `load_runbook(archetype, cfg)`. The `python-cli` runbook ships with the package. Custom runbooks can be added to a project-local `runbooks/` directory (configured via `AutopilotConfig.runbooks_dir`).

## Core Pipeline

**`sprint`** (`orchestrator.py: execute_sprint()`): Executes an approved `.dev/sprint.md` — loops through pending tasks sequentially. Each task: spawn worker agent → verify marked done → retry on failure up to `max_task_attempts`. Pass `--auto-approve` to bypass the approval check. Pass `--resume` to reset stuck projects and retry failed tasks.

**`build`** (`orchestrator.py: build_project()`): One-shot workflow: runs `plan` then `sprint`. Equivalent to `autopilot plan . && autopilot sprint --auto-approve .`. Pass `--context <file>` to seed the planner.

**`plan`**: Lazily runs roadmap agent if `.dev/roadmap.md` doesn't exist, then runs the planner agent to write `.dev/sprint.md`. The critic agent always runs if its config exists, followed by a judge loop (up to 2 rounds) that evaluates the plan and revises if needed. On judge READY, sets `approved: true` in sprint.md. Pass `--context <file>` to skip lazy research and seed the planner directly.

**`roadmap`**: Runs roadmap agent → writes `.dev/roadmap.md` with `goal:`, `archetype:`, and `validate:` frontmatter plus shipping steps. Uses research summary if available. The roadmap is the authoritative goal+validate artifact. Pass `--deep` to run deep research first. Pass `--topic "question"` or `--topic-file brief.md` to run topic research (writes `.dev/research/{slug}/report.md`, no roadmap written).

**`portfolio`**: Runs portfolio agent across all discovered projects → writes `<scan_dir>/.dev/portfolio.md`. Requires `--scan` or explicit paths.

## Key Patterns

- **Manifest format**: YAML frontmatter + markdown checkboxes at `.dev/sprint.md`. Task metadata persisted inline: `[id: foo]`, `[depends: bar]`, `[attempts: 2]`, `[status: failed]`, `[error: ...]`.
- **Session naming**: Every `run_agent()` call sets `extra_args={"session-name": "autopilot/{project}/{role}"}` so sessions appear distinctively in Claude Code's `/resume` history.
- **Project discovery**: `discover_projects()` finds dirs with `.dev/sprint.md`; `discover_all_projects()` finds any project-like dir (git, package.json, pyproject.toml, etc.).
- **Fork filtering**: In scan mode, non-owned repos are skipped by comparing git remote owner to detected user (`AUTOPILOT_GIT_USER` env → `git config autopilot.user` → `gh api user`). Use `--all` to disable.
- **Default cwd**: When no path arg is provided, autopilot defaults to the current directory for all modes.

## .dev Convention

All autopilot working files within a project live under `.dev/` (which should be in `.gitignore`):
- `.dev/sprint.md` — task manifest (`plan` output); used by `sprint` for worker loop
- `.dev/roadmap.md` — roadmap agent output; contains `goal:`, `archetype:`, and `validate:` frontmatter; used by `sprint` as the goal + validate definition
- `.dev/sprint-log.md` — sprint history, append-only, feeds planner context each sprint
- `.dev/project-summary.md` — researcher agent output
- `<scan_dir>/.dev/portfolio.md` — portfolio agent output

## Development Commands

```bash
uv pip install -e .                          # Install (editable)
autopilot sprint .                           # Execute approved sprint plan
autopilot sprint --auto-approve .            # Execute, bypassing approval check
autopilot sprint --resume .                  # Reset stuck projects and retry
autopilot build .                            # Plan then execute (one-shot)
autopilot build --context spec.md .          # Plan with context, then execute
autopilot plan .                             # Generate/improve manifest (plan + critic + judge)
autopilot roadmap .                          # Build shipping roadmap (goal + validate)
autopilot roadmap --deep .                   # Deep research then build roadmap
autopilot roadmap --topic "question" .       # Research a specific topic
autopilot sprint --scan ~/Projects           # Auto-discover and process all projects
uv run ruff check src/                      # Lint
uv run ruff format --check src/             # Format check
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
