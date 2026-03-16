# autopilot

[![PyPI](https://img.shields.io/pypi/v/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![CI](https://github.com/timainge/autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/timainge/autopilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![Docs](https://img.shields.io/badge/docs-github--pages-blue)](https://timainge.github.io/autopilot)

Autopilot is the outer loop for Claude Code. You describe what needs building; autopilot plans it, judges it, and runs it — task by task, sprint by sprint — without you sitting there typing "continue".

It has two modes:

- **Task execution** — write a task manifest, autopilot runs it. Good for well-defined work.
- **Strategy-driven sprints** — describe a goal, autopilot figures out the tasks, runs sprints, and checks whether the goal has been met. Good for open-ended projects.

---

## Install

```bash
pip install claude-autopilot
# or
uv pip install claude-autopilot
```

You need a Claude API key or a Claude Code subscription token:

```bash
# Option 1: API key
export ANTHROPIC_API_KEY=your-key-here

# Option 2: Claude Code subscription (Max/Pro)
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN=<token from above>
```

---

## Task Execution

The basic flow: research → roadmap → plan → run.

### Research and roadmap (optional but recommended)

```bash
autopilot research .    # analyzes codebase → .dev/project-summary.md
autopilot roadmap .     # identifies shipping target → .dev/roadmap.md
```

The researcher captures the tech stack, current state, and what's missing. The roadmap agent reads that and determines the right goal (production launch, library publish, blog post, etc.) with concrete phases and effort estimates. Neither step is required, but the planner produces much better tasks with this context.

### Plan

```bash
# Lazy: auto-runs research + roadmap first if they don't exist
autopilot plan .

# Seed with a TODO list, spec, or design doc — skips lazy research
autopilot plan --context TODO.md .

# Run a critic pass after planning
autopilot plan --review .
```

The planner writes `.dev/sprint.md` — a markdown file with YAML frontmatter and checkbox tasks. The `--review` flag runs a critic agent that checks file references, catches missing dependencies, and sharpens vague descriptions.

### Run

```bash
autopilot run .

# Auto-approve when the judge says READY
autopilot run --auto-approve .
```

On first run with `approved: false`, the judge evaluates the manifest and prints a READY / NOT_READY verdict with feedback. Set `approved: true` manually, or pass `--auto-approve` to let autopilot set it when the judge returns READY.

Once approved, autopilot loops through tasks sequentially. Each task spawns a fresh Claude Code session that implements the work, commits, and marks the checkbox done. Failed tasks are retried up to `max_task_attempts` times.

---

## Strategy-Driven Sprints

For open-ended goals — "get this library to a publishable state", "make this API production-ready" — the sprint workflow lets you define what done looks like and let autopilot figure out the steps.

### Strategize

```bash
autopilot strategize .

# Deep research first (web search + extended analysis)
autopilot strategize --deep .

# Seed with a spec or design doc
autopilot strategize --context spec.md .
```

The strategist writes `.dev/strategy.md` with:
- A **goal type**: `launch`, `publish`, or `complete`
- A **quality bar**: specific, measurable criteria (prefer commands over prose)
- `validate` commands: shell commands that must pass for the goal to be met

This file is both the sprint loop's input and its termination condition. Before sprints start, review and approve it by setting `approved: true`.

The `--deep` flag runs the deep-researcher agent first — web search, extended codebase analysis — producing richer context for the strategist. Worth the extra cost for unfamiliar codebases.

The roadmap (`autopilot roadmap .`) is a good optional step before strategizing — the strategist reads `.dev/roadmap.md` if it exists and uses it to ground the strategy in a realistic shipping target.

### Sprint

```bash
# Plan and run one sprint, then stop for review
autopilot sprint .

# Skip manual review between sprints
autopilot sprint --auto-approve .

# Loop until all validate commands pass
autopilot sprint --loop --auto-approve .
```

Each sprint:
1. Reads the strategy manifest
2. Plans a focused task manifest for the next increment (planner + optional critic)
3. Runs the worker loop
4. Runs the `validate` commands and asks the strategist to evaluate progress
5. Reports whether the strategy is satisfied

With `--loop`, sprints repeat until `strategy_satisfied` or `max_sprints` is reached.

---

## Multi-Repo Workflow

Every command works with `--scan` to operate across an entire directory:

```bash
autopilot research --scan ~/Projects
autopilot roadmap --scan ~/Projects
autopilot plan --scan ~/Projects
autopilot run --auto-approve --scan ~/Projects
autopilot strategize --scan ~/Projects
autopilot sprint --loop --auto-approve --scan ~/Projects
```

`portfolio` is multi-project only — it builds a cross-project index with analysis by tech stack, current state, and prioritized quick wins:

```bash
autopilot portfolio --scan ~/Projects
```

Output is written to `<scan_dir>/.dev/portfolio.md`.

### Fork filtering

When scanning, repos you don't own are skipped by default. Autopilot compares the git remote owner against your username. Configure via (checked in order):

```bash
export AUTOPILOT_GIT_USER=yourusername
# or
git config --global autopilot.user yourusername
# or have the gh CLI logged in (auto-detected)
```

Use `--all` to include forks and clones.

---

## Manifest Format

Two manifest files, two distinct purposes:

- **`.dev/sprint.md`** — task manifest, written by `plan`, read by `run`. Contains tasks with checkboxes. In sprint mode, overwritten each iteration by the sprint planner.
- **`.dev/strategy.md`** — strategy manifest, written by `strategize`, read by `sprint`. Contains a goal, quality bar, and `validate` commands.

Both use the same YAML frontmatter + markdown format. Add `.dev/` to `.gitignore` — it contains orchestration state, not source code.

### Frontmatter fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | dir name | Project display name |
| `approved` | bool | false | Human approval gate |
| `status` | string | pending | pending / active / stuck / completed |
| `worktree` | bool | false | Run each task in an isolated git worktree |
| `branch_prefix` | string | autopilot | Branch prefix when `worktree: true` |
| `max_budget_usd` | float | 5.0 | Budget cap per project run |
| `max_task_attempts` | int | 3 | Max retries per task before marking failed |
| `goal` | string | — | Strategy goal type: launch / publish / complete |
| `archetype` | string | — | Project archetype (e.g. `python-cli`) for bundled runbooks |
| `validate` | list | — | Shell commands that must pass for strategy completion |

### Task format

Tasks are level-3 headings with a checkbox, a slug ID, optional inline metadata, and a body:

```markdown
### [ ] task-slug-id

Body text describing what the worker agent should do. Can be multiple paragraphs,
include file paths, acceptance criteria, implementation notes, etc.

---

### [ ] another-task [depends: task-slug-id]

Body text for this task.

---

### [x] completed-task
```

- **IDs** are the heading text — must be slug format (`lowercase-with-dashes`)
- **Dependencies** use `[depends: task-id-1, task-id-2]` inline in the heading
- **Retry metadata** (`[attempts: N]`, `[status: failed]`, `[error: ...]`) is written by autopilot and should not be edited manually

---

## Agent Roles

Agent configs live in `src/autopilot/agents/*.md` — YAML frontmatter + system prompt. Sessions appear in Claude Code's `/resume` history as `autopilot/projectname/role`.

| Role | Command | What it does |
|------|---------|--------------|
| `judge` | `run` | Evaluates manifest readiness, prints READY / NOT_READY |
| `worker` | `run` | Executes a task: implements, tests, commits |
| `planner` | `plan` | Creates `.dev/sprint.md` with structured tasks |
| `critic` | `plan --review` | Reviews plan adversarially, edits manifest directly |
| `researcher` | `research` | Analyzes codebase → `.dev/project-summary.md` |
| `deep-researcher` | `strategize --deep` | Extended analysis with web search |
| `roadmap` | `roadmap` | Shipping target + concrete phases → `.dev/roadmap.md` |
| `strategist` | `strategize` / `sprint` | Writes `.dev/strategy.md` (create mode); evaluates sprint completion against it (evaluate mode) |
| `portfolio` | `portfolio` | Cross-project index → `<scan_dir>/.dev/portfolio.md` |

### Custom roles

Add markdown files to `agents/` (use `--agents-dir` for a custom directory):

```markdown
---
name: reviewer
description: Reviews completed tasks for quality
allowed_tools: [Read, Glob, Bash, Grep]
permission_mode: default
max_turns: 20
max_budget_usd: 0.50
---

You review recently completed tasks for quality...
```

---

## Design Notes

**Why the Agent SDK, not CLI pipes?**
The Agent SDK wraps the Claude Code CLI programmatically — same tools, proper message streaming, error handling, no heredoc escaping. Each `query()` call is a fresh Claude Code session.

**Why sequential, not parallel?**
Simpler to debug, cheaper, and avoids merge conflicts. Parallelism via git worktrees can be added later.

**Why a human approval gate?**
The judge evaluates readiness, but a human must explicitly set `approved: true` (or pass `--auto-approve`). This prevents runaway execution on half-baked plans.

**Why markdown manifests, not YAML/JSON?**
The manifest doubles as project documentation. YAML frontmatter gives structured config; the markdown body gives rich context that both humans and agents can read naturally.

**What's the difference between roadmap and strategize?**
`roadmap` is a discursive exploration: what's the right shipping target, how long will it take, what phases are involved. It's human-readable context that grounds the planner. `strategize` is a precise termination condition: a tight goal statement, measurable quality bar, and `validate` commands that the sprint loop uses to decide when to stop. The strategist reads the roadmap if it exists — run roadmap first for the best results.
