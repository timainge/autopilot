# Getting Started

This guide walks you through installing autopilot, writing your first manifest, and executing your first automated task session.

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

Verify the install:

```bash
autopilot --version
# autopilot 0.1.0
```

## Option A: Let AI Write the Manifest

The fastest path is to let autopilot generate the manifest for you.

**Step 1 — Analyse the project:**

```bash
autopilot research .
```

This writes `.dev/project-summary.md` — a structured analysis of your codebase.

**Step 2 — Build a roadmap:**

```bash
autopilot roadmap .
```

Writes `.dev/roadmap.md` — a concrete list of steps to ship.

**Step 3 — Generate the manifest:**

```bash
autopilot plan .
```

Writes `.dev/autopilot.md`. Review it, adjust tasks as needed, then proceed to the Execute section below.

## Option B: Write the Manifest Yourself

Create `.dev/autopilot.md` in your project root:

```markdown
---
name: my-project
approved: false
status: active
max_budget_usd: 5.0
max_task_attempts: 3
---

# My Project — v1.0

## Context

A short description of what this project does and what this sprint achieves.

## Tasks

### [ ] setup-linting

Add ruff to the project dev dependencies and configure it in `pyproject.toml`.
Run `ruff check src/` to verify it works.

**Done**: `ruff check src/` exits 0 with no errors.

---

### [ ] write-tests [depends: setup-linting]

Write unit tests for the main module using pytest.

**Done**: `pytest tests/ -v` exits 0 with at least 5 passing tests.

---

### [ ] update-readme [depends: write-tests]

Rewrite README.md with the current feature set, install instructions, and usage examples.

**Done**: README.md contains an install section and a usage section.
```

**Key frontmatter fields:**

| Field | Meaning |
|-------|---------|
| `approved: false` | Tells autopilot to run the judge first |
| `max_budget_usd` | Hard cap on LLM spend per run (in USD) |
| `max_task_attempts` | How many times to retry a failing task |

## The Judge Phase

With `approved: false`, running autopilot triggers the judge agent:

```bash
autopilot .
```

The judge reads your manifest and evaluates it. If the plan looks coherent, complete, and safe, it will say so. If not, it will explain what's missing or ambiguous.

Review the judge's output in your terminal. When you're satisfied, open `.dev/autopilot.md` and change:

```yaml
approved: false
```

to:

```yaml
approved: true
```

### Auto-Approve

If you trust the plan and want to skip the manual approval step:

```bash
autopilot --auto-approve .
```

The judge still runs, but if it returns a "ready" verdict, autopilot sets `approved: true` automatically.

## The Worker Phase

Once `approved: true`, run autopilot again:

```bash
autopilot .
```

Tasks execute sequentially. Each task:

1. Spawns a fresh Claude Code session with the task description as context
2. Claude Code does the work — writes code, runs commands, commits changes
3. The worker verifies the task is marked done (checkbox checked in the manifest)
4. If not done after the session ends, autopilot retries up to `max_task_attempts` times

Progress is printed to the terminal as tasks complete. The manifest file is updated live — you can open it at any time to see what's been done.

## Multi-Repo Workflows

To process multiple projects at once:

```bash
# Discover and run all projects with a manifest under ~/Projects
autopilot --scan ~/Projects

# Research + plan all projects (no manifest required)
autopilot research --scan ~/Projects
autopilot plan --scan ~/Projects
```

See [CLI Reference](cli-reference.md) for the full flag list.

## What's in `.dev/`

Autopilot keeps all its working files under `.dev/`:

```
.dev/
├── autopilot.md          # The manifest (you edit this)
├── project-summary.md    # Research output
└── roadmap.md            # Roadmap output
```

Add `.dev/` to your `.gitignore` — these files are local working state, not source code.

## Next Steps

- [Manifest Format](manifest-format.md) — complete reference for all manifest fields and task syntax
- [CLI Reference](cli-reference.md) — every flag explained with examples
- [Concepts](concepts.md) — deeper explanation of the judge/worker design
