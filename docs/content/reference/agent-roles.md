# Agent Roles

> The built-in agents that power autopilot's pipelines, and how to define your own.

Each agent role is defined by a markdown file in `src/autopilot/agents/` with YAML frontmatter specifying the system prompt, allowed tools, budget, and permission mode.

Sessions appear in Claude Code's `/resume` history as `autopilot/<projectname>/<role>` — every session is inspectable after the fact.

---

## Built-in roles

| Role | Used by | What it does |
|------|---------|-------------|
| `worker` | `sprint` | Executes a task: implements, tests, commits, marks done. |
| `planner` | `plan`, `build`, `ralph` | Creates `.dev/sprint.md` from roadmap + context. |
| `judge` | `plan` (internal) | Evaluates manifest readiness. Returns READY or NOT_READY with feedback. |
| `critic` | `plan` (internal) | Adversarial review of the generated plan. Edits manifest directly. |
| `researcher` | (internal) | Analyses codebase → `.dev/project-summary.md`. |
| `deep-researcher` | `roadmap --deep` | Extended analysis with web search and ecosystem scan. |
| `roadmap` | `roadmap`, `ralph` | Two modes: **create** (writes `.dev/roadmap.md`) and **evaluate** (checks if goal is met). |
| `portfolio` | `portfolio` | Cross-project analysis → `<scan_dir>/.dev/portfolio.md`. |

### worker

The core execution agent. Receives a task description, implements the work, runs verification commands, commits, and marks the checkbox done in `sprint.md`.

Each task spawns a fresh worker session. The worker has broad tool access: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`.

### planner

Reads `.dev/roadmap.md` as its primary input (plus sprint log for context on what's been done) and produces a structured `.dev/sprint.md`. The planner scopes tasks to the current phase of the roadmap.

### judge

Evaluates whether a plan is ready to execute. Reads the manifest and returns:
- **READY** — plan is coherent, complete, and safe. Sets `approved: true`.
- **NOT_READY** — plan has issues. Returns feedback. The planner revises and the judge re-evaluates (up to 2 rounds).

The judge never auto-approves unless `--auto-approve` is passed.

### critic

Adversarial reviewer that runs after the planner (if its config exists) and before the judge. Edits the manifest directly to fix issues it finds — task ordering, missing done criteria, ambiguous descriptions.

### roadmap (create mode)

Analyses the project and writes `.dev/roadmap.md` with:
- `goal:` — the appropriate shipping target (`launch`, `publish`, `complete`)
- `archetype:` — project type for runbook selection
- `validate:` — shell commands that define "done"
- Body — a concrete shipping roadmap with phases and steps

### roadmap (evaluate mode)

Used by `ralph` after each sprint. Reads the roadmap plus the sprint log and determines whether the goal has been met. Returns `GOAL_MET` or a description of what's still missing.

One agent, one artifact, two perspectives.

---

## Custom roles

Add a markdown file to `src/autopilot/agents/` (or a custom `--agents-dir` directory):

```markdown
---
name: reviewer
description: Reviews completed tasks for quality and consistency
allowed_tools: [Read, Glob, Bash, Grep]
permission_mode: default
max_turns: 20
max_budget_usd: 0.50
---

You are a code reviewer. After each sprint, read the changes made
in the last N commits and assess quality, consistency with existing
patterns, and potential issues. Write your findings to .dev/review.md.
```

### Frontmatter fields

| Field | Description |
|-------|-------------|
| `name` | Role identifier. Used in session naming and log output. |
| `description` | Short description of what this role does. |
| `allowed_tools` | List of Claude Code tools the agent may use. |
| `permission_mode` | `default` or `bypassPermissions` (use sparingly). |
| `max_turns` | Maximum conversation turns per session. |
| `max_budget_usd` | Budget cap for a single session. |

To use a custom agents directory:

```bash
autopilot plan --agents-dir ./my-agents .
```

---

## Runbooks

Agent roles can load bundled runbooks for additional context. The `python-cli` runbook ships with autopilot. Custom runbooks can be added to a project-local `runbooks/` directory.

The roadmap agent selects the appropriate runbook based on the `archetype:` field in `roadmap.md`. The `archetype` value maps to a runbook file (e.g. `archetype: python-cli` → `python-cli.md`).

Configure the runbooks directory in `autopilot.toml`:

```toml
[tool.autopilot]
runbooks_dir = "runbooks"
```
