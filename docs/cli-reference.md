# CLI Reference

## Usage

```bash
autopilot [OPTIONS] [PATH]
```

`PATH` defaults to the current directory.

## Modes

### Default Run

```bash
autopilot .
```

Runs the judge (if not approved) or worker (if approved) on the project.

### Plan Mode

```bash
autopilot --plan .
autopilot --plan --context brief.md .
autopilot --plan --review .
```

Generates or improves `.dev/autopilot.md`. Lazily runs research and roadmap agents first if their outputs don't exist. Pass `--context` to seed the planner directly. Pass `--review` to run the critic agent after planning.

### Research Mode

```bash
autopilot --research .
```

Analyses the project and writes `.dev/project-summary.md`. Incremental: re-running detects changes since the last analysis.

### Roadmap Mode

```bash
autopilot --roadmap .
```

Builds a shipping roadmap and writes `.dev/roadmap.md`. Uses research output if available.

### Portfolio Mode

```bash
autopilot --portfolio --scan ~/Projects
autopilot --portfolio path/to/project1 path/to/project2
```

Runs portfolio analysis across multiple projects and writes `<scan_dir>/.dev/portfolio.md`.

### Scan Mode

```bash
autopilot --scan ~/Projects
```

Auto-discovers and processes all projects under the given directory.

## Options

| Flag | Description |
|------|-------------|
| `--auto-approve` | Skip human approval gate; set `approved: true` automatically |
| `--dry-run` | Show what would run without executing |
| `--resume` | Resume a paused session |
| `--all` | Disable fork filtering (process all repos, not just owned ones) |
| `--context FILE` | Seed the planner with a context file (use with `--plan`) |
| `--review` | Run the critic agent after planning (use with `--plan`) |
| `--scan DIR` | Auto-discover projects under DIR |
| `--version` | Print version and exit |
