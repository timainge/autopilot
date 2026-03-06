# Session Pilot

Autonomous project session orchestrator. Reads project manifests, evaluates
readiness via an LLM judge, and executes tasks sequentially through Claude Code
via the Anthropic Agent SDK.

## The Problem

You have hobby projects with clear plans but spend your time as a "human cron
job" — opening Claude Code, saying "continue with the plan", and babysitting
sessions. Session Pilot automates this outer loop.

## How It Works

```
┌─────────────┐     ┌──────────┐     ┌─────────────────┐
│  autopilot  │────▶│  Judge   │────▶│ "READY" / "NOT  │
│ (each run)  │     │  Agent   │     │  READY + why"   │
│             │     └──────────┘     └─────────────────┘
│  if approved│     ┌──────────┐     ┌─────────────────┐
│  ──────────▶│────▶│  Worker  │────▶│ Task complete,  │
│  next task  │     │  Agent   │     │ commit, mark ✓  │
│             │     └──────────┘     └─────────────────┘
│  loop ──────│
└─────────────┘
```

Each run has two phases:

1. **Judge** — if `approved: false`, evaluates whether the plan is ready for
   autonomous execution. Never auto-approves; you must set `approved: true`.
2. **Worker** — if `approved: true`, runs the next pending task, verifies it
   was marked done, retries on failure, and loops until complete or stuck.

## Prerequisites

```bash
uv pip install -e .
```

The Agent SDK bundles the Claude Code CLI. You need one of:

```bash
# Option 1: API key (pay-per-token billing)
export ANTHROPIC_API_KEY=your-key-here

# Option 2: Claude Code subscription (Max/Pro plan billing)
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN=<token from above>
```

## Quick Start

### 1. Add a manifest to your project

Create `.dev/autopilot.md` in your project (and add `.dev/` to `.gitignore`):

```markdown
---
name: "My Project"
approved: false
status: pending
max_budget_usd: 5.0
max_task_attempts: 3
---

# My Project

Description of what you're building and any relevant context.

## Tasks

- [ ] First task to implement
- [ ] Second task [depends: first-task-to-implement]
- [ ] Third task [depends: second-task]
```

See `autopilot.example.md` for a full example.

### 2. Generate a plan (optional)

Instead of writing a manifest by hand, let the planner agent create one:

```bash
# Generate a plan from the codebase
autopilot --plan /path/to/project

# Seed with an existing TODO list, spec, or planning doc
autopilot --plan --context /path/to/TODO.md /path/to/project
```

The planner explores the codebase and writes `.dev/autopilot.md` with structured
tasks. `--context` accepts any file — a TODO list, design doc, meeting notes, etc.

### 3. Evaluate and approve

```bash
autopilot /path/to/your/project
```

The judge evaluates the manifest and prints a READY / NOT_READY verdict with
feedback. If NOT_READY, revise based on the suggestions and run again.

Once the plan looks good, set `approved: true` in the manifest and run again.
Autopilot switches to worker mode and executes tasks one by one, committing
each when done and retrying failures up to `max_task_attempts` times.

### 4. Process multiple projects

```bash
# Explicit paths
autopilot ~/Projects/project-a ~/Projects/project-b

# Scan a directory for projects with .dev/autopilot.md
autopilot --scan ~/Projects

# Preview what would run
autopilot --scan ~/Projects --dry-run
```

## Research & Portfolio Modes

These are standalone modes for exploring projects without a manifest.

### Research a project

Runs the researcher agent to analyze a project and write findings to
`.dev/research/summary.md`:

```bash
autopilot --research /path/to/project
autopilot --research --scan ~/Projects        # all projects in directory
autopilot --research --all --scan ~/Projects  # include forks/clones
autopilot --research --scan ~/Projects --dry-run
```

When scanning, forks and cloned repos are skipped by comparing the git remote
owner against your username. Configure via (checked in this order):

```bash
export AUTOPILOT_GIT_USER=yourusername
# or
git config --global autopilot.user yourusername
# or have the gh CLI logged in (auto-detected)
```

### Build a portfolio overview

Builds a cross-project index with analysis by tech stack, state, and
prioritized quick wins. Projects with existing research summaries are indexed
from those; the rest get a quick assessment.

```bash
autopilot --portfolio --scan ~/Projects
autopilot --portfolio --scan ~/Projects --dry-run
```

Output is written to `<scan_dir>/.dev/portfolio.md`.

## Manifest Format

The manifest is markdown with YAML frontmatter at `.dev/autopilot.md`. Add
`.dev/` to the project's `.gitignore` — it contains orchestration state, not
source code.

### Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | dir name | Project display name |
| `approved` | bool | false | Human approval gate — must be set manually |
| `status` | string | pending | pending / active / paused / completed / failed |
| `max_budget_usd` | float | 5.0 | Budget cap per project run |
| `max_task_attempts` | int | 3 | Max retries per task before marking failed |
| `worktree` | bool | false | Reserved: git worktree isolation |
| `branch_prefix` | string | autopilot | Reserved: prefix for task branches |

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
- **Retry metadata** (`[attempts: N]`, `[status: failed]`, `[error: ...]`) is
  written by autopilot and persists across reloads — don't edit these manually

## Agent Configs

Agent roles are markdown files with YAML frontmatter in `agents/`. Each file
defines a role's system prompt and SDK options.

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
- **researcher** — analyzes a project and writes `.dev/research/summary.md`
- **portfolio** — builds a cross-project overview at `<scan_dir>/.dev/portfolio.md`

### Custom Roles

Create new agent roles by adding markdown files to `agents/`:

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

## Design Decisions

**Why the Agent SDK, not CLI pipes?**
The Agent SDK wraps the Claude Code CLI programmatically — same tools, same
capabilities, but with proper message streaming, error handling, and no
heredoc escaping issues. Each `query()` call spawns a fresh Claude Code session.

**Why sequential, not parallel?**
These are hobby projects. Sequential execution is simpler to debug, cheaper
(one session at a time), and avoids merge conflicts. Parallelism can be added
later via git worktrees.

**Why a human approval gate?**
Autonomous agents need guardrails. The judge evaluates readiness, but a human
must explicitly set `approved: true`. This prevents runaway execution on
half-baked plans.

**Why markdown manifests, not YAML/JSON?**
Readability. The manifest doubles as project documentation. YAML frontmatter
gives structured config, while the markdown body provides rich context that
both humans and agents can read naturally.

## Future

- Git worktree isolation for parallel task execution
- Budget tracking across sessions
- Webhook/notification on completion or failure
- Specialised agents (test architect, dependency updater, etc.)
