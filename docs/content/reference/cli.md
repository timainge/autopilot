# CLI Reference

> All autopilot commands, flags, and options.

```bash
autopilot <command> [OPTIONS] [PATH...]
```

`PATH` defaults to the current directory when omitted. Most commands accept `--scan DIR` to operate across an entire directory.

---

## `sprint` — Execute tasks

Executes the approved `.dev/sprint.md` task manifest.

```bash
autopilot sprint .
autopilot sprint --auto-approve .
autopilot sprint --resume .
```

Loops through pending tasks sequentially. Each task spawns a fresh Claude Code session. Failed tasks are retried up to `max_task_attempts` times.

| Flag | Description |
|------|-------------|
| `--auto-approve` | Skip the manual approval gate. If `approved: false`, sets it to `true` and proceeds. |
| `--resume` | Reset stuck projects (`status: in_progress`) and retry failed tasks. |
| `--scan DIR` | Auto-discover all projects with `.dev/sprint.md` under `DIR` and sprint each one. |
| `--all` | Disable fork filtering when scanning. |
| `--dry-run` | Show which projects would run without executing. |

---

## `plan` — Generate a task manifest

Runs the planner agent to create or update `.dev/sprint.md`.

```bash
autopilot plan .
autopilot plan --context brief.md .
```

Lazily runs `roadmap` first if `.dev/roadmap.md` doesn't exist. A critic agent reviews the plan automatically (if its config exists). A judge evaluates readiness and sets `approved: true` on approval, after up to 2 revision rounds.

| Flag | Description |
|------|-------------|
| `--context FILE` | Seed the planner with a file (spec, brief, TODO list). Skips lazy research. |
| `--scan DIR` | Plan all discovered projects under `DIR`. |
| `--all` | Disable fork filtering when scanning. |
| `--dry-run` | Preview without executing. |

---

## `build` — Plan then sprint (one-shot)

Combines `plan` + `sprint --auto-approve` in a single command.

```bash
autopilot build .
autopilot build --context spec.md .
```

Equivalent to: `autopilot plan . && autopilot sprint --auto-approve .`

| Flag | Description |
|------|-------------|
| `--context FILE` | Seed the planner with a context file. |
| `--scan DIR` | Build all projects under `DIR`. |

---

## `roadmap` — Build a shipping roadmap

Runs the roadmap agent and writes `.dev/roadmap.md`.

```bash
autopilot roadmap .
autopilot roadmap --deep .
autopilot roadmap --topic "How should I structure the auth layer?" .
autopilot roadmap --topic-file research-brief.md .
```

In default mode, the roadmap agent analyses the project and produces a `roadmap.md` with `goal:`, `archetype:`, and `validate:` frontmatter plus a shipping roadmap body.

`--deep` runs a deep-researcher pass first (web search + ecosystem scan) before building the roadmap.

`--topic` and `--topic-file` run targeted research and write a report to `.dev/research/{slug}/report.md` — no roadmap is produced. Use these when you need to answer a specific question before committing to a roadmap.

| Flag | Description |
|------|-------------|
| `--deep` | Run deep research (web search + codebase analysis) before building the roadmap. |
| `--topic TEXT` | Research a specific question. Writes a report, not a roadmap. |
| `--topic-file FILE` | Like `--topic`, but reads the question from a file. |
| `--scan DIR` | Build roadmaps for all projects under `DIR`. |
| `--all` | Disable fork filtering when scanning. |
| `--dry-run` | Preview without executing. |

---

## `ralph` — Autonomous outer loop

Runs `plan → sprint → validate → evaluate` in a loop until the goal is met, the sprint limit is reached, or tasks fail.

```bash
autopilot ralph .
```

Requires `.dev/roadmap.md` with a `validate:` block. See the [Ralph guide](../guides/scenarios/ralph.md) for details.

| Flag | Description |
|------|-------------|
| `--scan DIR` | Run ralph on all projects under `DIR` that have a `.dev/roadmap.md`. |
| `--all` | Disable fork filtering when scanning. |

---

## `portfolio` — Cross-project analysis

Runs portfolio analysis across multiple projects and writes a portfolio report.

```bash
autopilot portfolio --scan ~/Projects
autopilot portfolio ~/Projects/api ~/Projects/cli-tool
```

Requires `--scan` or explicit paths. Auto-generates `.dev/roadmap.md` for projects that lack one (using deep research if no existing research artifacts). Output written to `<scan_dir>/.dev/portfolio.md`.

| Flag | Description |
|------|-------------|
| `--scan DIR` | Discover projects under `DIR` and write portfolio to `DIR/.dev/portfolio.md`. |
| `--all` | Disable fork filtering. |
| `--dry-run` | Preview without executing. |

---

## Global flags

These apply to all commands:

| Flag | Description |
|------|-------------|
| `--agents-dir DIR` | Use a custom directory of agent role configs instead of the bundled ones. |
| `--all` | Disable fork filtering — include repos you don't own when using `--scan`. |
| `--dry-run` | Show what would run without executing any agents. |
| `--version` | Print the installed version and exit. |

---

## Fork filtering

When using `--scan`, autopilot skips repos you don't own by comparing the git remote owner to your detected username. Configure your username via (checked in order):

```bash
# 1. Environment variable
export AUTOPILOT_GIT_USER=yourusername

# 2. Git config
git config --global autopilot.user yourusername

# 3. Auto-detected from gh CLI (if logged in)
```

Use `--all` to disable and include all repos.

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key for authentication. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code subscription token (alternative to API key). |
| `AUTOPILOT_GIT_USER` | Your GitHub username for fork filtering. Overrides all other detection methods. |
