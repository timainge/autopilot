# Portfolio Overview

> Scan an entire directory of projects, auto-generate roadmaps for each, and produce a prioritized cross-project portfolio report. Good for understanding what to work on next across many repos.

**When to use this:** You have a `~/Projects` directory full of repos in various states of completion. You want a single doc that tells you: what's there, what state each project is in, and where to focus.

---

## Running portfolio

```bash
autopilot portfolio --scan ~/Projects
```

This does:

1. **Discovers** all project-like directories (git repos, packages with `pyproject.toml` or `package.json`, etc.)
2. **Skips forks** you don't own (compares git remote owner to your username)
3. **Auto-generates** `.dev/roadmap.md` for any project that lacks one (using deep research if no existing research artifacts)
4. **Runs the portfolio agent** across all projects, reading each `roadmap.md` as its primary input
5. **Writes** `~/Projects/.dev/portfolio.md` — a cross-project index with analysis

---

## Output

The portfolio report at `<scan_dir>/.dev/portfolio.md` includes:

- **Project inventory** — name, goal type, archetype, current state
- **Status summary** — what's been done, what's next
- **Quick wins** — highest-value, lowest-effort opportunities across all projects
- **Prioritization** — ranked recommendations for where to focus

---

## Explicit paths

Instead of `--scan`, you can pass explicit paths:

```bash
autopilot portfolio ~/Projects/api ~/Projects/cli-tool ~/Projects/blog
```

Useful when you want a portfolio of a specific subset, not everything in a directory.

---

## Fork filtering

When scanning, autopilot detects your GitHub username and skips repos you don't own. Configure your username via any of:

```bash
# Environment variable (highest priority)
export AUTOPILOT_GIT_USER=yourusername

# Git config
git config --global autopilot.user yourusername

# Automatic detection (requires gh CLI logged in)
```

Use `--all` to disable filtering and include all repos:

```bash
autopilot portfolio --all --scan ~/Projects
```

---

## Combining with ralph

Once you have a portfolio and know what to work on, run ralph on the highest-priority project:

```bash
# Get the overview
autopilot portfolio --scan ~/Projects

# Pick the winner and go
autopilot ralph ~/Projects/my-api
```

Or run ralph across everything and let it drive:

```bash
autopilot ralph --scan ~/Projects
```

---

## Keeping the portfolio fresh

The portfolio is a snapshot. Re-run it after completing a sprint or ralph run to update the analysis:

```bash
autopilot portfolio --scan ~/Projects
```

The portfolio agent reads the latest `roadmap.md` from each project, so updates to those files are picked up automatically.
