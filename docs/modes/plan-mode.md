# Plan Mode

Plan mode generates or improves your project manifest (`.dev/autopilot.md`).

## Usage

```bash
autopilot --plan .
```

## What It Does

1. Lazily runs the researcher agent if `.dev/project-summary.md` doesn't exist
2. Lazily runs the roadmap agent if `.dev/roadmap.md` doesn't exist
3. Runs the planner agent to write `.dev/autopilot.md`

## Options

Pass `--context <file>` to seed the planner with a specific context file, skipping lazy research:

```bash
autopilot --plan --context brief.md .
```

Pass `--review` to run the critic agent after planning:

```bash
autopilot --plan --review .
```
