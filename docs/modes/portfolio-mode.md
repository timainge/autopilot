# Portfolio Mode

Portfolio mode runs analysis across multiple projects and produces a summary.

## Usage

```bash
autopilot --portfolio --scan ~/Projects
autopilot --portfolio path/to/project1 path/to/project2
```

## What It Does

Runs the portfolio agent across all discovered projects and writes `<scan_dir>/.dev/portfolio.md`.

## Fork Filtering

In scan mode, non-owned repos are skipped by comparing the git remote owner to the detected user. Use `--all` to disable fork filtering and process all repos.
