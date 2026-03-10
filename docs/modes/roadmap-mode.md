# Roadmap Mode

Roadmap mode produces a concrete shipping roadmap for your project.

## Usage

```bash
autopilot --roadmap .
```

## What It Does

Runs the roadmap agent, which determines the right shipping target (prod launch, library publish, blog post, etc.) and lists concrete steps. Output is written to `.dev/roadmap.md`.

Uses research output (`.dev/project-summary.md`) if available.
