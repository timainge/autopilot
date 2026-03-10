# autopilot

[![PyPI](https://img.shields.io/pypi/v/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![CI](https://github.com/timainge/autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/timainge/autopilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![Docs](https://img.shields.io/badge/docs-github--pages-blue)](https://timainge.github.io/autopilot)

Autonomous project session orchestrator for Claude Code. You write a plan; autopilot runs it. It reads project manifests (`.dev/autopilot.md`), evaluates whether the plan is ready for autonomous execution via a judge agent, then loops through tasks sequentially using the Anthropic Agent SDK — each task gets its own Claude Code session, commits its work, and marks itself done. The result is an automated outer loop for hobby project development: no more opening Claude Code, typing "continue with the plan", and babysitting sessions.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│                        autopilot run                             │
│                                                                  │
│  optional prep       planning          execution                 │
│                                                                  │
│  --research .   ──▶  --plan .    ──▶  Judge phase               │
│  --roadmap .          (lazy:            │                        │
│                       runs research     │ READY / NOT_READY      │
│                       + roadmap if      ▼                        │
│                       missing)        Approve gate               │
│                                       (manual or --auto-approve) │
│                                         │                        │
│                                         ▼                        │
│                                       Worker loop                │
│                                       task → commit → ✓          │
│                                       task → commit → ✓          │
│                                       ...                        │
└──────────────────────────────────────────────────────────────────┘
```

**Phase overview:**

1. **Research** (`--research`) — Researcher agent analyzes the codebase and writes `.dev/project-summary.md`: tech stack, current state, what's done, what's missing.
2. **Roadmap** (`--roadmap`) — Roadmap agent reads the research summary and writes `.dev/roadmap.md` with a concrete shipping target and next steps.
3. **Plan** (`--plan`) — Planner agent creates `.dev/autopilot.md` with structured tasks. Without `--context`, it lazily runs research + roadmap first if those artifacts don't exist yet.
4. **Judge** — On each run with `approved: false`, the judge agent evaluates whether the manifest is ready for autonomous execution and prints a READY / NOT_READY verdict with feedback.
5. **Approve** — A human sets `approved: true` in the manifest, or pass `--auto-approve` and autopilot sets it automatically when the judge returns READY.
6. **Worker loop** — With `approved: true`, autopilot runs tasks one by one: each task spawns a fresh Claude Code session, the session implements the task, commits, and marks the checkbox done. Failures are retried up to `max_task_attempts` times.

---

## Install

```bash
pip install claude-autopilot
# or
uv pip install claude-autopilot
```

The Agent SDK bundles the Claude Code CLI. You need one of:

```bash
# Option 1: API key (pay-per-token billing)
export ANTHROPIC_API_KEY=your-key-here

# Option 2: Claude Code subscription (Max/Pro plan billing)
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN=<token from above>
```

---

## Single-Project Workflow

### 1. Research the project (recommended)

```bash
autopilot --research .
```

Runs the researcher agent, writes `.dev/project-summary.md`. Captures tech stack, current state, what's done, and what's missing. Re-running is safe and cheap — the agent checks the stored commit hash against the current state and does a partial update if little has changed, or a full re-analysis if the project has moved significantly.

### 2. Build a shipping roadmap (recommended)

```bash
autopilot --roadmap .
```

Reads the research summary (or does a quick assessment if it doesn't exist yet), then writes `.dev/roadmap.md` identifying the right shipping target (production launch, library publish, blog post, etc.) and the concrete steps to get there. The planner uses this as context to produce higher-quality tasks.

### 3. Generate a plan

```bash
# Recommended: auto-runs research + roadmap if artifacts don't exist
autopilot --plan .

# Seed with an existing TODO list, spec, or design doc
autopilot --plan --context TODO.md .

# Run a critic pass after planning
autopilot --plan --review .
autopilot --plan --review --context TODO.md .
```

The planner agent explores the codebase and writes `.dev/autopilot.md` with structured, dependency-linked tasks.

Without `--context`, the planner automatically runs research + roadmap first if `.dev/project-summary.md` and `.dev/roadmap.md` don't already exist (lazy research). This is the recommended default — richer context produces better tasks.

`--context` accepts any file: a TODO list, design doc, meeting notes, or spec. Pass it to skip lazy research and seed the planner directly.

`--review` runs a critic agent after planning. The critic reads the plan adversarially — verifying file references exist, checking for missing dependencies, and sharpening vague descriptions. It edits the manifest directly. Adds roughly 50% more cost but catches blind spots the planner missed.

See [Manifest Format](#manifest-format) for the full syntax reference.

### 4. Evaluate and approve

```bash
autopilot .
```

The judge evaluates the manifest and prints a READY / NOT_READY verdict with specific feedback. If NOT_READY, revise the manifest based on the feedback and run again.

Once the plan is ready:

```bash
# Option A: edit manually
# Open .dev/autopilot.md and set approved: true

# Option B: auto-approve when judge says READY
autopilot --auto-approve .
```

The approval gate exists by design — the judge evaluates readiness, but a human (or explicit `--auto-approve`) must unlock execution. This prevents runaway execution on half-baked plans.

### 5. Execute

```bash
autopilot .
```

With `approved: true`, autopilot enters worker mode and runs tasks sequentially. Each task:
- Spawns a fresh Claude Code session with full tool access
- Implements the task, runs tests, commits the result
- Marks the checkbox `[x]` in the manifest
- Retries up to `max_task_attempts` times on failure

---

## Multi-Repo Workflow

`--scan` maps every single-project action across an entire directory. All flags that work on a single project work with `--scan`. Autopilot discovers projects by finding directories that look like active repos (git-initialized, with a `package.json`, `pyproject.toml`, etc.).

### Research all projects

```bash
autopilot --research --scan ~/Projects
autopilot --research --all --scan ~/Projects   # include forks/clones
autopilot --research --scan ~/Projects --dry-run
```

### Build roadmaps

```bash
autopilot --roadmap --scan ~/Projects
autopilot --roadmap --all --scan ~/Projects
```

### Portfolio overview

```bash
autopilot --portfolio --scan ~/Projects
```

Portfolio is multi-project only — there's no single-project equivalent. It builds a cross-project index with analysis by tech stack, current state, and prioritized quick wins. Projects with existing research summaries are indexed from those; the rest get a quick in-place assessment. Output is written to `<scan_dir>/.dev/portfolio.md`.

### Plan and execute at scale

```bash
autopilot --plan --scan ~/Projects
autopilot --scan ~/Projects              # judge + worker loop on all projects
autopilot --auto-approve --scan ~/Projects
autopilot --scan ~/Projects --dry-run
```

### Fork filtering

When scanning, repos you don't own are skipped by default. Autopilot compares the git remote owner against your username. Configure via (checked in this order):

```bash
export AUTOPILOT_GIT_USER=yourusername
# or
git config --global autopilot.user yourusername
# or have the gh CLI logged in (auto-detected)
```

Use `--all` to include forks and clones.

---

## Manifest Format

The manifest is a markdown file with YAML frontmatter at `.dev/autopilot.md`. Add `.dev/` to the project's `.gitignore` — it contains orchestration state, not source code.

### Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | dir name | Project display name |
| `approved` | bool | false | Human approval gate — set manually or via `--auto-approve` |
| `status` | string | pending | pending / active / paused / completed / failed |
| `max_budget_usd` | float | 5.0 | Budget cap per project run |
| `max_task_attempts` | int | 3 | Max retries per task before marking failed |

### Task Format

Tasks are standard markdown checkboxes under a `## Tasks` heading:

```markdown
## Tasks

- [ ] Implement the thing
- [ ] Another thing [depends: implement-the-thing]
- [ ] Custom ID task [id: custom-id, depends: implement-the-thing]
- [x] Already done task
```

- **IDs** are auto-derived by slugifying the title, or set explicitly with `[id: ...]`
- **Dependencies** use `[depends: task-id-1, task-id-2]`
- **Status** is tracked by the checkbox: `[ ]` = pending, `[x]` = done
- **Retry metadata** (`[attempts: N]`, `[status: failed]`, `[error: ...]`) is written by autopilot and persists across reloads — don't edit these manually

### Full Example

```markdown
---
name: "My Project"
approved: false
status: pending
max_budget_usd: 5.0
max_task_attempts: 3
---

# My Project

Description of what you're building and any relevant context the worker agent needs.

## Tasks

- [ ] Set up the database schema [id: db-schema]
- [ ] Implement the API endpoints [depends: db-schema]
- [ ] Write tests [depends: db-schema]
- [ ] Update README [depends: implement-api-endpoints]
```

---

## Agent Configs

Agent roles are markdown files with YAML frontmatter in `src/autopilot/agents/`. Each file defines a role's system prompt and SDK options.

Sessions appear in Claude Code's `/resume` history as `autopilot/projectname/role` (e.g., `autopilot/myproject/worker`, `autopilot/myproject/planner`) so you can trace which session did what.

### Frontmatter Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Role identifier |
| `description` | string | What this agent does |
| `allowed_tools` | list | Claude Code tools to enable |
| `permission_mode` | string | default / acceptEdits / bypassPermissions |
| `max_turns` | int | Max conversation turns |
| `max_budget_usd` | float | Budget cap per invocation |
| `model` | string | Model override (optional) |

### Included Roles

- **judge** — evaluates manifest readiness, suggests improvements
- **worker** — executes tasks: reads context, implements, tests, commits
- **planner** — creates or improves task plans (`--plan` flag)
- **critic** — reviews plans adversarially (`--plan --review`)
- **researcher** — analyzes a project and writes `.dev/project-summary.md`
- **portfolio** — builds a cross-project overview at `<scan_dir>/.dev/portfolio.md`
- **roadmap** — builds a shipping roadmap per project at `.dev/roadmap.md`

### Custom Roles

Create new agent roles by adding markdown files to `agents/` (use `--agents-dir` to point to a custom directory):

```markdown
---
name: reviewer
description: Reviews completed tasks for quality
allowed_tools: [Read, Glob, Bash, Grep]
permission_mode: default
max_turns: 20
max_budget_usd: 0.50
---

# Code Reviewer

You review recently completed tasks for quality...
```

---

## Design Decisions

**Why the Agent SDK, not CLI pipes?**
The Agent SDK wraps the Claude Code CLI programmatically — same tools, same capabilities, but with proper message streaming, error handling, and no heredoc escaping issues. Each `query()` call spawns a fresh Claude Code session.

**Why sequential, not parallel?**
These are hobby projects. Sequential execution is simpler to debug, cheaper (one session at a time), and avoids merge conflicts. Parallelism can be added later via git worktrees.

**Why a human approval gate?**
Autonomous agents need guardrails. The judge evaluates readiness, but a human must explicitly set `approved: true` (or pass `--auto-approve`). This prevents runaway execution on half-baked plans.

**Why markdown manifests, not YAML/JSON?**
Readability. The manifest doubles as project documentation. YAML frontmatter gives structured config, while the markdown body provides rich context that both humans and agents can read naturally.
