# Getting Started

## Install

```bash
pip install claude-autopilot
```

Or with uv:

```bash
uv pip install claude-autopilot
```

## Your First Manifest

Create a `.dev/autopilot.md` file in your project:

```markdown
---
name: my-project
approved: false
status: active
max_budget_usd: 5.0
max_task_attempts: 3
---

# My Project — v1.0.0

## Tasks

### [ ] setup-project

Initialize the project structure and install dependencies.

**Done**: Project runs without errors.
```

## Running autopilot

1. Create your manifest
2. Run the judge: `autopilot .` (with `approved: false`, it evaluates readiness)
3. Review the judge's feedback and set `approved: true` when ready
4. Run again: `autopilot .` — tasks execute sequentially

## Research Mode

Analyse your project without a manifest:

```bash
autopilot --research .
```

## Plan Mode

Let AI generate the manifest for you:

```bash
autopilot --plan .
```
