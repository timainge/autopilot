# CLI Reference

Autopilot uses a subcommand-based interface. The default subcommand is `run` — if you omit a subcommand and pass a path, autopilot injects `run` automatically.

```bash
autopilot [SUBCOMMAND] [OPTIONS] [PATHS...]
```

`PATHS` defaults to the current directory when omitted.

---

## `run` — Execute Tasks (Default)

```bash
autopilot run .
autopilot .           # equivalent — 'run' is the default subcommand
```

Runs the judge (if `approved: false`) or worker (if `approved: true`) on each project.

### Run Options

| Flag | Description |
|------|-------------|
| `--auto-approve` | If the judge returns "ready", automatically set `approved: true` and proceed to the worker phase without human intervention. |
| `--resume` | Reset a stuck project (status `in_progress`) and retry failed tasks. Use this to recover from interrupted runs. |
| `--dry-run` | Show which projects would be processed and their current status without executing any agents. |
| `--scan DIR` | Auto-discover all projects with a `.dev/autopilot.md` under `DIR` and process them all. |

### Examples

```bash
# Run on current directory
autopilot .

# Run and skip the approval prompt
autopilot --auto-approve .

# Scan all projects in ~/Projects
autopilot --scan ~/Projects

# Preview what would run without executing
autopilot --dry-run --scan ~/Projects

# Recover from a stuck run
autopilot --resume .
```

---

## `plan` — Generate or Improve the Manifest

```bash
autopilot plan .
autopilot plan --context brief.md .
autopilot plan --review .
```

Runs the planner agent to create or improve `.dev/autopilot.md`. If `.dev/project-summary.md` or `.dev/roadmap.md` don't exist, they are generated first (lazy research).

### Plan Options

| Flag | Description |
|------|-------------|
| `--context FILE` | Seed the planner with a file (e.g. an existing TODO list, design doc, or brief). Skips the lazy research phase. |
| `--review` | Run the critic agent after planning to verify and refine the generated manifest. |
| `--dry-run` | Show which projects would be planned without running the planner. |
| `--scan DIR` | Discover all project directories under `DIR` and plan each one. |

### Examples

```bash
# Generate manifest for current project
autopilot plan .

# Seed with an existing brief
autopilot plan --context .dev/brief.md .

# Generate and then critique
autopilot plan --review .

# Plan all projects in a directory
autopilot plan --scan ~/Projects
```

---

## `research` — Analyse the Project

```bash
autopilot research .
```

Runs the researcher agent and writes `.dev/project-summary.md`. Re-running is incremental: autopilot compares the stored commit hash against the current state and does a full or partial re-analysis as needed.

### Research Options

| Flag | Description |
|------|-------------|
| `--all` | Disable fork filtering — include repos you don't own when scanning. |
| `--dry-run` | Show which projects would be researched without running the agent. |
| `--scan DIR` | Discover all project directories under `DIR` and research each one. |

### Examples

```bash
# Analyse current project
autopilot research .

# Research all projects, including forks
autopilot research --all --scan ~/Projects
```

---

## `roadmap` — Build a Shipping Roadmap

```bash
autopilot roadmap .
```

Runs the roadmap agent and writes `.dev/roadmap.md`. Uses `.dev/project-summary.md` if it exists. The roadmap identifies the right shipping target (PyPI publish, blog post, production launch, etc.) and lists the concrete steps to get there.

### Roadmap Options

| Flag | Description |
|------|-------------|
| `--all` | Disable fork filtering when scanning. |
| `--dry-run` | Preview without executing. |
| `--scan DIR` | Process all projects under `DIR`. |

---

## `portfolio` — Cross-Project Overview

```bash
autopilot portfolio --scan ~/Projects
autopilot portfolio path/to/project1 path/to/project2
```

Runs portfolio analysis across multiple projects and writes `<scan_dir>/.dev/portfolio.md`. Requires either `--scan` or explicit project paths.

### Portfolio Options

| Flag | Description |
|------|-------------|
| `--all` | Disable fork filtering. |
| `--dry-run` | Preview without executing. |
| `--scan DIR` | Discover projects under `DIR` and write portfolio to `DIR/.dev/portfolio.md`. |

---

## Global Options

These flags apply to all subcommands:

| Flag | Description |
|------|-------------|
| `--scan DIR` | Auto-discover projects under `DIR`. Behavior varies by subcommand (see above). |
| `--agents-dir DIR` | Use a custom directory of agent role configs instead of the bundled ones. |
| `--dry-run` | Preview what would be done without executing any agents. |
| `--version` | Print the installed version and exit. |

---

## `--version`

```bash
autopilot --version
# autopilot 0.1.0
```

---

## `--scan` and Fork Filtering

When using `--scan`, autopilot detects your GitHub username (via `AUTOPILOT_GIT_USER` env var, `git config autopilot.user`, or `gh api user`) and skips repos you don't own. This prevents accidentally running on cloned third-party projects.

Use `--all` to disable this filter:

```bash
autopilot research --all --scan ~/Projects
```

To set your username permanently:

```bash
git config --global autopilot.user your-github-username
# or
export AUTOPILOT_GIT_USER=your-github-username
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AUTOPILOT_GIT_USER` | Your GitHub username for fork filtering. Overrides all other detection methods. |

---

## Config File

Autopilot reads `~/.config/autopilot/config.toml` (global) and `autopilot.toml` (per-project). See [Concepts](concepts.md) for the full config schema.
