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
│  pilot.py   │────▶│  Judge   │────▶│ "READY" / "NOT  │
│ (for each   │     │  Agent   │     │  READY + why"   │
│  project)   │     └──────────┘     └─────────────────┘
│             │
│  if approved│     ┌──────────┐     ┌─────────────────┐
│  ──────────▶│────▶│  Worker  │────▶│ Task complete,  │
│  next task  │     │  Agent   │     │ commit, mark ✅  │
│             │     └──────────┘     └─────────────────┘
│  loop ──────│
└─────────────┘
```

1. **Discover** — find projects with `.dev/autopilot.md` manifests
2. **Judge** — if not approved, evaluate plan readiness via LLM judge
3. **Execute** — for approved projects, run the next pending task
4. **Track** — tasks are marked done in the manifest; failures recorded with retry context

## Prerequisites

```bash
# Install from source
uv pip install -e .

# Or install dependencies directly
pip install claude-agent-sdk pyyaml
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

### 2. Run the judge

```bash
autopilot /path/to/your/project
```

The judge evaluates whether the plan is ready. If it says READY, set
`approved: true` in the manifest.

### 3. Run the worker loop

```bash
autopilot /path/to/your/project
```

With `approved: true`, autopilot starts executing tasks sequentially.

### 4. Research projects

Before creating a manifest, you can run the researcher agent to analyze a project
and get a recommendation (finish & launch, archive, blog post, etc.):

```bash
# Research a single project
autopilot --research /path/to/project

# Research all projects in a directory (skips forks/clones by default)
autopilot --research --scan ~/Projects

# Include forks and cloned repos
autopilot --research --all --scan ~/Projects

# Preview which projects would be researched
autopilot --research --scan ~/Projects --dry-run
```

Results are written to `.dev/research/summary.md` in each project.

When scanning, forks and cloned repos are skipped by comparing the git remote
owner against your username. Set your username via (checked in this order):

```bash
export AUTOPILOT_GIT_USER=yourusername
# or
git config --global autopilot.user yourusername
# or have the gh CLI logged in (auto-detected)
```

### 5. Build a portfolio overview

After researching projects (or even without), build a cross-project overview
with an index table, analysis by tech stack/state/recommendation, and
prioritized quick wins:

```bash
# Portfolio of all your projects
autopilot --portfolio --scan ~/Projects

# Preview
autopilot --portfolio --scan ~/Projects --dry-run
```

Output is written to `<scan_dir>/.dev/portfolio.md`. Projects with existing
research summaries are indexed from those; the rest get a quick assessment.

### 6. Process multiple projects

```bash
# Explicit paths
autopilot ~/Projects/project-a ~/Projects/project-b

# Scan a directory
autopilot --scan ~/Projects

# Dry run — see what would happen
autopilot --scan ~/Projects --dry-run
```

## Manifest Format

The manifest is markdown with YAML frontmatter. It lives at `.dev/autopilot.md`
in each project directory. The `.dev/` directory should be added to the project's
`.gitignore` — it contains orchestration state, not source code.

### Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | dir name | Project display name |
| `approved` | bool | false | Human approval gate — must be set manually |
| `status` | string | pending | pending / active / paused / completed / failed |
| `worktree` | bool | false | Reserved: use git worktrees for task isolation |
| `branch_prefix` | string | autopilot | Reserved: prefix for task branches |
| `max_budget_usd` | float | 5.0 | Budget cap for the project |
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
- **planner** — creates or improves task plans (invoke manually)
- **researcher** — analyzes a project and writes a research summary with recommendations
- **portfolio** — builds a cross-project portfolio overview with index table and synthesis

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
- Integration with picobot for scheduled execution
- Specialised agents (test architect, dependency updater, etc.)
