# Manifest Format

Full reference for `.dev/autopilot.md`.

## Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | directory name | Project name |
| `approved` | bool | `false` | Whether the manifest is approved for execution |
| `status` | string | `active` | Project status (`active`, `paused`, `done`) |
| `max_budget_usd` | float | `5.0` | Maximum spend per run in USD |
| `max_task_attempts` | int | `3` | Maximum retries per task on failure |

## Task Format

Tasks use markdown heading + checkbox syntax:

```markdown
### [ ] task-id

Task description here. Can include any markdown.

**Done**: Verifiable completion criteria.
```

When complete, the checkbox becomes `[x]`:

```markdown
### [x] task-id
```

## Inline Metadata

Tasks can carry inline metadata tags on the heading line or body:

- `[depends: other-task]` — declare a dependency
- `[attempts: 2]` — number of execution attempts (written by autopilot)
- `[status: failed]` — task status (written by autopilot)
- `[error: ...]` — last error message (written by autopilot)

## Full Example

```markdown
---
name: my-project
approved: true
status: active
max_budget_usd: 8.0
max_task_attempts: 3
---

# My Project

## Tasks

### [x] setup

Initialize the repo.

**Done**: `git status` shows clean state.

---

### [ ] implement-feature [depends: setup]

Build the main feature.

**Done**: Tests pass.
```

## .gitignore Note

Add `.dev/` to your `.gitignore` — autopilot working files should not be committed:

```gitignore
.dev/
```
