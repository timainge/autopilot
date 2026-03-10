# Research Mode

Research mode analyses your project and produces a summary document.

## Usage

```bash
autopilot --research .
```

## What It Does

Runs the researcher agent, which reads your codebase and writes `.dev/project-summary.md`.

## Incremental Analysis

Re-running research mode compares the stored commit hash against the current state. If the project has changed significantly, it performs a full re-analysis; otherwise it does a partial update.
