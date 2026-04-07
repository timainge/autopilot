# autopilot

[![PyPI](https://img.shields.io/pypi/v/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![CI](https://github.com/timainge/autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/timainge/autopilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![Docs](https://img.shields.io/badge/docs-github--pages-blue)](https://timainge.github.io/autopilot)

Autopilot is the outer loop for Claude Code. You describe what needs building; autopilot plans it, executes it task by task, and checks whether the goal was met — without you sitting there typing "continue".

---

## How it works

Autopilot runs a three-stage cycle:

```
roadmap  →  plan  →  sprint
  ↑                    |
  └──── evaluate ←─────┘
```

**Roadmap** — defines the goal, the shipping target, and what "done" looks like (validation commands). Optional but makes everything downstream sharper.

**Plan** — a planner agent reads the roadmap and writes `.dev/sprint.md`: a set of structured tasks. A critic reviews it, a judge approves it. No execution until the plan is approved.

**Sprint** — each task in the manifest gets a fresh Claude Code session. The worker implements, commits, and marks the task done. Failed tasks retry up to a configured limit.

**Ralph** is the outer loop that drives this cycle autonomously — planning a sprint, executing it, running validation, evaluating whether the goal is met, and repeating until it is.

---

## Install

```bash
pip install claude-autopilot
# or
uv pip install claude-autopilot
```

Requires a Claude API key from [console.anthropic.com](https://console.anthropic.com):

```bash
export ANTHROPIC_API_KEY=your-key-here
```

---

## Quick start

**One-shot build** — plan then execute in a single command:

```bash
autopilot build .
autopilot build --context spec.md .   # seed the planner with a spec or TODO list
```

**Step by step** — more control:

```bash
autopilot roadmap .          # optional: build a goal + validate spec
autopilot plan .             # write + approve the task manifest
autopilot sprint .           # execute the approved manifest
```

**Fully autonomous loop** — keeps going until the goal is met:

```bash
autopilot roadmap .          # required for ralph: defines the goal and validate commands
autopilot ralph .            # plan → sprint → evaluate, repeat
```

---

## Commands

### `roadmap`

Writes `.dev/roadmap.md` — the goal, archetype, validation commands, and shipping phases. Used
as the primary input for planning and as the termination condition for ralph.

```bash
autopilot roadmap .                          # assess the project and write a roadmap
autopilot roadmap --deep .                   # run deep research (web + ecosystem) first
autopilot roadmap --topic "question" .       # research a specific question → .dev/research/
autopilot roadmap --topic-file brief.md .    # same, from a file
```

### `plan`

Runs the planner → critic → judge pipeline and writes an approved `.dev/sprint.md`.

```bash
autopilot plan .                             # auto-runs roadmap first if it doesn't exist
autopilot plan --context TODO.md .           # seed with a spec or todo list, skip research
```

The critic reviews the plan adversarially. The judge evaluates readiness: if NOT_READY, the
planner revises once with the judge's feedback and the judge re-evaluates. When approved,
`approved: true` is set in the manifest automatically.

### `sprint`

Executes the approved `.dev/sprint.md` task manifest. Each task spawns a fresh Claude Code
session.

```bash
autopilot sprint .
autopilot sprint --auto-approve .            # skip the approval check
autopilot sprint --resume .                  # reset stuck projects, retry failed tasks
```

### `build`

Shorthand for `plan` + `sprint --auto-approve` in one command.

```bash
autopilot build .
autopilot build --context spec.md .
```

### `ralph`

The fully autonomous outer loop. Requires `.dev/roadmap.md` (run `autopilot roadmap .` first).

```bash
autopilot ralph .
autopilot ralph --auto-approve .
```

Each iteration: plan a sprint → execute tasks → run `validate` commands from roadmap frontmatter
→ evaluate whether the goal is met. Stops when:
- The evaluator returns `GOAL_MET`
- Tasks fail (appends a deferred investigation task to `roadmap.md`)
- `max_sprints` is reached

### `portfolio`

Builds a cross-project index — goal, tech stack, current state, and prioritised quick wins.
Auto-generates `.dev/roadmap.md` for any project that lacks one before building.

```bash
autopilot portfolio --scan ~/Projects
autopilot portfolio path/to/proj-a path/to/proj-b
```

Output: `<scan_dir>/.dev/portfolio.md`.

---

## Multi-project scanning

Every command works with `--scan` to operate across a directory of projects:

```bash
autopilot roadmap --scan ~/Projects
autopilot plan --scan ~/Projects
autopilot sprint --auto-approve --scan ~/Projects
autopilot ralph --scan ~/Projects
```

Repos you don't own are skipped by default. Autopilot compares the git remote owner against
your username (checked in order: `AUTOPILOT_GIT_USER` env, `git config autopilot.user`, `gh`
CLI auth). Use `--all` to include forks and clones.

---

## Configuration

### Per-project: `autopilot.toml`

```toml
[autopilot]
max_budget_usd = 10.0
max_task_attempts = 3
max_sprints = 5
```

### Global: `~/.config/autopilot/config.toml`

Same format. Per-project config takes precedence.

### Manifest frontmatter

`.dev/sprint.md` and `.dev/roadmap.md` use YAML frontmatter for structured config:

| Field | File | Default | Description |
|-------|------|---------|-------------|
| `name` | sprint | dir name | Project display name |
| `approved` | sprint | false | Approval gate — must be true before sprint runs |
| `status` | sprint | pending | pending / active / stuck / completed |
| `max_budget_usd` | sprint | 5.0 | Budget cap per sprint |
| `max_task_attempts` | sprint | 3 | Max retries per failed task |
| `goal` | roadmap | — | Goal type: launch / publish / complete |
| `archetype` | roadmap | — | Project archetype (e.g. `python-cli`) |
| `validate` | roadmap | — | Shell commands that must pass for goal completion |

Add `.dev/` to `.gitignore` — it contains orchestration state, not source code.

### Task format

Tasks in `.dev/sprint.md` are level-3 headings with a checkbox, a slug ID, and an optional
body:

```markdown
### [ ] create-api-client

Implement `src/client.py` with a `get()` and `post()` method using `httpx`.
Use the base URL from `config.py`. Raise `APIError` on non-2xx responses.

**Done**: `pytest tests/test_client.py` passes.

---

### [ ] add-retry-logic [depends: create-api-client]

Add exponential backoff to the client using `tenacity`. Max 3 retries,
starting at 1s. Log each retry attempt at WARNING level.

---

### [x] completed-task
```

- IDs are the heading text — must be `lowercase-with-dashes`
- Dependencies: `[depends: task-id]` or `[depends: a, b]` inline in the heading
- Retry metadata (`[attempts: N]`, `[status: failed]`, `[error: ...]`) is written by autopilot — don't edit manually

---

## Agent roles

Agent configs live in `src/autopilot/agents/*.md` — YAML frontmatter + system prompt. Sessions
appear in Claude Code's `/resume` history as `autopilot/projectname/role`.

| Role | Invoked by | What it does |
|------|-----------|--------------|
| `planner` | `plan`, `build`, `ralph` | Writes `.dev/sprint.md` |
| `critic` | `plan`, `build`, `ralph` | Reviews the plan adversarially |
| `judge` | `plan`, `build`, `ralph` | Approves or rejects the plan |
| `worker` | `sprint`, `build`, `ralph` | Executes a task, commits |
| `roadmap` | `roadmap`, `ralph` | Writes `.dev/roadmap.md`; evaluates goal completion |
| `researcher` | (lazy, before `plan`) | Analyses codebase → `.dev/project-summary.md` |
| `deep-researcher` | `roadmap --deep` | Extended web research before roadmapping |
| `portfolio` | `portfolio` | Cross-project index → `.dev/portfolio.md` |

### Custom roles

Drop a markdown file into `agents/` (or use `--agents-dir` to point to a custom directory):

```markdown
---
name: reviewer
description: Reviews completed tasks for quality
allowed_tools: [Read, Glob, Bash, Grep]
permission_mode: default
max_turns: 20
max_budget_usd: 0.50
---

You are a code reviewer. You read recently completed tasks and assess quality...
```

---

## Design notes

**Why the Agent SDK, not CLI pipes?**
The SDK wraps Claude Code programmatically — same tools, proper message streaming, error
handling. Each `query()` call is a fresh Claude Code session with clean context.

**Why sequential tasks, not parallel?**
Simpler to debug, cheaper, and avoids merge conflicts. Parallel execution via git worktrees is
planned for a future release.

**Why a human approval gate?**
The judge evaluates readiness, but a human must explicitly set `approved: true` (or pass
`--auto-approve`). This prevents runaway execution on half-baked plans.

**Why markdown manifests?**
The manifest doubles as project documentation. YAML frontmatter gives structured config; the
markdown body gives context that humans and agents can both read naturally.
