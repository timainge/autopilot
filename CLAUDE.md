# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autopilot is an autonomous project session orchestrator. It reads project manifests (`.dev/autopilot.md`), evaluates readiness via an LLM judge agent, and executes tasks sequentially through Claude Code via the Anthropic Agent SDK. It automates the outer loop of hobby project development.

## .dev Convention

All autopilot working files within a project live under `.dev/`:
- `.dev/autopilot.md` — project manifest (tasks, config, plan)
- `.dev/research/summary.md` — researcher agent output
- Projects should add `.dev/` to their `.gitignore`

## Development Commands

```bash
# Install (editable)
uv pip install -e .

# Run
autopilot /path/to/project              # Process one project
autopilot --scan ~/Projects             # Auto-discover projects
autopilot --scan ~/Projects --dry-run   # Preview only
autopilot --research /path/to/project   # Research a project
autopilot --research --scan ~/Projects  # Research all projects
python -m autopilot                     # Alternative entry point

# Lint
ruff check src/
ruff format --check src/
```

There are no tests yet.

## Architecture

The codebase is a single Python package at `src/autopilot/` (~760 LOC total).

**Core pipeline** (`orchestrator.py`): Two-phase flow per project:
1. **Judge phase** — if `approved: false`, runs the judge agent to evaluate manifest readiness. Never auto-approves; human must set `approved: true`.
2. **Worker phase** — if `approved: true`, loops through pending tasks sequentially. Each task: spawn worker agent → verify task marked done → handle retries on failure.

**Research mode** (`--research`): Standalone mode that runs the researcher agent to analyze a project and write findings to `.dev/research/summary.md`. Doesn't require a manifest — discovers projects by common markers (.git, package.json, etc.).

**Module responsibilities:**
- `cli.py` — argparse CLI, async entry point, project discovery
- `orchestrator.py` — judge/worker/researcher pipeline, task execution loop, retry logic
- `manifest.py` — parse/load/write manifests (YAML frontmatter + markdown checkboxes), task dependency resolution, agent config loading
- `prompts.py` — prompt builders for judge/worker/researcher, verdict parsing
- `agent.py` — thin wrapper around `claude_agent_sdk.query()`, streams messages, tracks cost
- `models.py` — dataclasses: `Task`, `Manifest`, `AgentConfig`, `AgentResult`
- `log.py` — timestamped status logging

**Agent role configs** (`src/autopilot/agents/*.md`): Markdown files with YAML frontmatter defining system prompts, allowed tools, budget, and permission mode for each agent role (judge, worker, planner).

## Key Patterns

- **Manifest format**: Markdown with YAML frontmatter at `.dev/autopilot.md`. Tasks are markdown checkboxes with inline metadata like `[id: foo]`, `[depends: bar]`, `[attempts: 2]`, `[status: failed]`, `[error: ...]`.
- **Task IDs**: Auto-slugified from title (`slugify()` in `manifest.py`) unless overridden with `[id: ...]`.
- **Task persistence**: Status and error metadata are persisted as inline bracket notation in the manifest file, not just in memory. This survives reloads.
- **Agent execution**: Each `run_agent()` call spawns a fresh Claude Code session via the SDK's `query()` async generator. Cost is tracked per invocation.
- **Dependency resolution**: `get_next_task()` finds the first pending task whose dependencies are all done and hasn't exceeded max attempts.

## Documentation

When adding or changing features that affect CLI usage, agent roles, or the manifest format, update `README.md` to match. The README is the primary user-facing documentation.

## Code Style

- Python 3.11+, async/await throughout
- Ruff linter: line length 100, rules `E, F, I, N, W, UP`
- Dataclasses (not Pydantic)
- Type hints with `X | None` union syntax (not `Optional`)
