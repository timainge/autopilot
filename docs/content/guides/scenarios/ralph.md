# Ralph: Autonomous Loop

> Fully autonomous development. Ralph runs plan → sprint → evaluate in a loop until the goal is met or you've hit the sprint limit. Set it and walk away.

**When to use this:** You have a clear goal with verifiable success criteria and you want autopilot to drive the entire development loop autonomously — figuring out tasks, running them, checking if the goal is met, and planning the next sprint if it isn't.

---

## Prerequisites

Ralph requires a `.dev/roadmap.md` with a `validate:` block. This is the termination condition: when these commands pass, ralph considers the goal met.

```bash
# Build the roadmap first
autopilot roadmap .         # quick assessment
autopilot roadmap --deep .  # with deep research
```

Verify `.dev/roadmap.md` has:

```yaml
---
goal: publish
archetype: python-cli
validate:
  - uv build
  - uv run twine check dist/*
---
```

If the validate commands don't accurately reflect "done", ralph will loop forever (or until `max_sprints`). Spend time getting these right.

---

## Running ralph

```bash
autopilot ralph .
```

Each iteration:

1. **Plan** — runs planner + critic + judge to produce an approved `sprint.md`
2. **Sprint** — runs the worker loop on all tasks
3. **Validate** — runs the `validate:` commands from `roadmap.md`
4. **Evaluate** — asks the roadmap agent whether the goal has been met

If `GOAL_MET`, ralph stops. If not, it loops.

---

## How it terminates

Ralph stops when any of these conditions are true:

| Condition | What happens |
|-----------|-------------|
| `GOAL_MET` | Evaluator says the goal is achieved. |
| Task failure | A task fails after `max_task_attempts` retries. Ralph appends a deferred investigation task to `roadmap.md` and stops. |
| `max_sprints` reached | The sprint count limit from config is hit. |
| Plan not approved | The judge loop fails to produce an approved plan. |

After a task failure, check the error in `.dev/sprint.md`, fix the underlying issue, and re-run `autopilot ralph .` (or `autopilot sprint --resume .` to retry just the failed task).

---

## Configuration

In `autopilot.toml` or the project's `pyproject.toml`:

```toml
[tool.autopilot]
max_sprints = 5          # max iterations before giving up
max_budget_usd = 20.0    # total budget cap across all sprints
max_task_attempts = 3    # retries per task
```

Or in `.dev/sprint.md` frontmatter (applies to the current sprint):

```yaml
---
max_budget_usd: 10.0
max_task_attempts: 2
---
```

---

## Watching a ralph run

Ralph logs each phase to the terminal with timestamps:

```
[10:42:01] ralph: starting sprint 1
[10:42:01] plan: running planner
[10:42:45] plan: judge approved
[10:42:45] sprint: executing 4 tasks
[10:43:12] sprint: task add-ruff ✓
[10:44:08] sprint: task write-tests ✓
[10:45:31] sprint: task update-readme ✓
[10:46:02] sprint: task configure-ci ✓
[10:46:02] validate: running 2 commands
[10:46:05] evaluate: GOAL_MET after 1 sprint
```

Sessions appear in Claude Code's `/resume` history as `autopilot/<project>/<role>`, so you can inspect any session after the fact.

---

## When ralph gets stuck

If ralph stops due to a task failure, it writes a deferred investigation task to `roadmap.md`:

```markdown
### Deferred: investigate task failure

Task `write-tests` failed after 3 attempts. Error: `pytest: no tests ran`.
Investigate and resolve before the next ralph run.
```

Read the error, fix the task or the underlying issue, then re-run `autopilot ralph .`.

---

## Multi-project ralph

```bash
autopilot ralph --scan ~/Projects
```

Runs ralph on every project in `~/Projects` that has a `.dev/roadmap.md`. Projects without a roadmap are skipped (use `autopilot roadmap --scan ~/Projects` first).

---

## Next steps

For a cross-project overview before deciding what to ralph, see [Portfolio Overview](portfolio.md).
