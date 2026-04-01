# Quick Start

> Get autopilot installed and execute your first task end-to-end.

## Prerequisites

- Python 3.11 or later
- [Claude Code](https://claude.ai/code) installed and authenticated
- A project directory you want to automate

## Install

=== "pip"

    ```bash
    pip install claude-autopilot
    ```

=== "uv"

    ```bash
    uv pip install claude-autopilot
    ```

Verify:

```bash
autopilot --version
```

## Set up authentication

You need either a Claude API key or a Claude Code subscription token:

=== "API key"

    ```bash
    export ANTHROPIC_API_KEY=your-key-here
    ```

=== "Claude Code subscription"

    ```bash
    claude setup-token
    export CLAUDE_CODE_OAUTH_TOKEN=<token from above>
    ```

## Option A: Let autopilot write the plan

The fastest path if you have an existing project:

```bash
cd my-project

# Build a shipping roadmap (analyses your project first)
autopilot roadmap .

# Generate a task manifest from the roadmap
autopilot plan .

# Review .dev/sprint.md, then execute
autopilot sprint .
```

When `autopilot plan` runs, it writes `.dev/sprint.md` with a list of tasks. A judge agent evaluates the plan — if approved, `approved: true` is set automatically. Then `autopilot sprint` executes the tasks.

## Option B: Write the plan yourself

Create `.dev/sprint.md` in your project root:

```markdown
---
name: my-project
approved: true
max_budget_usd: 5.0
---

### [ ] add-ruff

Add ruff to the project. Install it as a dev dependency in `pyproject.toml`,
add a `[tool.ruff]` config section with `line-length = 100`, and run
`uv run ruff check src/` to verify.

**Done**: `uv run ruff check src/` exits 0.
```

Then run:

```bash
autopilot sprint .
```

## What happens during execution

1. Autopilot reads `.dev/sprint.md` and finds unchecked tasks
2. Each task spawns a fresh Claude Code session with the task description as context
3. Claude Code does the work — writes code, runs commands, commits
4. The worker verifies the task checkbox is checked in the manifest
5. Failed tasks are retried up to `max_task_attempts` times

Progress is printed to the terminal. The manifest is updated live — you can open it any time to see what's done.

## Next steps

- [Plan & Sprint scenario](scenarios/plan-and-sprint.md) — the full plan-then-execute workflow
- [Manifest Format](../reference/manifest-format.md) — complete task syntax reference
- [CLI Reference](../reference/cli.md) — all commands and flags
