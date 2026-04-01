# Manifest Format

> Complete syntax reference for `sprint.md` and `roadmap.md`.

Autopilot uses two manifest files, both stored under `.dev/` in your project root:

| File | Written by | Read by | Purpose |
|------|-----------|---------|---------|
| `.dev/sprint.md` | `plan` (or you) | `sprint`, `ralph` | Task list for the current sprint |
| `.dev/roadmap.md` | `roadmap` (or you) | `plan`, `ralph`, `portfolio` | Goal, archetype, validate commands, and shipping roadmap |

Both use YAML frontmatter + markdown format. Add `.dev/` to `.gitignore`:

```gitignore
.dev/
```

---

## sprint.md

### Frontmatter

```yaml
---
name: my-project
approved: false
status: pending
max_budget_usd: 5.0
max_task_attempts: 3
worktree: false
branch_prefix: autopilot
---
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | dir name | Project display name. Used in log output and session naming. |
| `approved` | bool | `false` | Whether the manifest is approved for execution. Set by the judge or manually. |
| `status` | string | `pending` | `pending` / `active` / `stuck` / `completed`. Autopilot manages this. |
| `max_budget_usd` | float | `5.0` | Budget cap per run in USD. Execution stops if exceeded. |
| `max_task_attempts` | int | `3` | Retries per task before marking it failed. |
| `worktree` | bool | `false` | Run each task in an isolated git worktree. |
| `branch_prefix` | string | `autopilot` | Branch prefix when `worktree: true`. |

### Task syntax

Tasks are H3 headings with a checkbox, a slug ID, optional inline metadata, and a body:

```markdown
### [ ] task-slug-id

Body text describing what the worker should do. Any markdown is valid.
Include file paths, acceptance criteria, implementation notes.

**Done**: A verifiable statement of what "complete" means.

---

### [ ] another-task [depends: task-slug-id]

Body text for this task.
```

**Task ID** — the text after `[ ]`. Must be `lowercase-with-dashes` and unique within the manifest.

**Checkbox states:**

| Syntax | Meaning |
|--------|---------|
| `### [ ] task-id` | Pending |
| `### [x] task-id` | Complete (written by the worker) |

**Body** — everything between the heading and the next `---` separator or heading. Write it as instructions for the worker agent. Always include a `**Done**:` line with a verifiable criterion.

### Inline metadata tags

Appended to the heading line. Autopilot writes retry/error tags during execution; `[depends: ...]` is written by you.

```markdown
### [ ] my-task [depends: other-task] [attempts: 2] [status: failed] [error: exit code 1]
```

| Tag | Written by | Meaning |
|-----|-----------|---------|
| `[depends: id]` | You | Task waits until `id` is complete. Comma-separate multiple: `[depends: a, b]`. |
| `[attempts: N]` | Autopilot | Number of execution attempts so far. |
| `[status: failed]` | Autopilot | Task failed after `max_task_attempts` retries. |
| `[error: ...]` | Autopilot | Last error message from a failed attempt. |

### Full example

```markdown
---
name: my-api
approved: true
max_budget_usd: 8.0
max_task_attempts: 3
---

# My API — Sprint 1

## Context

FastAPI service. This sprint adds JWT auth and prepares for a v0.1.0 release.

### [ ] install-deps

Install `python-jose[cryptography]` and `passlib[bcrypt]`:

```bash
uv add python-jose[cryptography] passlib[bcrypt]
```

**Done**: `uv run python -c "import jose, passlib"` exits 0.

---

### [ ] implement-auth [depends: install-deps]

Add `POST /auth/login` to `src/api/routes/auth.py`.
Accept `{"email": str, "password": str}`, return JWT on success, 401 on failure.

**Done**: `pytest tests/test_auth.py -v` exits 0 with all tests passing.

---

### [x] update-readme

Rewrote README with install instructions and API overview.
```

---

## roadmap.md

### Frontmatter

```yaml
---
goal: publish
archetype: python-cli
validate:
  - uv build
  - uv run twine check dist/*
  - pip install dist/*.whl && my-tool --version
---
```

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | Goal type: `launch` (production deployment), `publish` (package registry), or `complete` (general completion). |
| `archetype` | string | Project archetype (e.g. `python-cli`, `web-api`) used to load bundled runbooks. |
| `validate` | list | Shell commands that must pass for the goal to be considered met. Used by `ralph` to check termination. |

### Body

The roadmap body is a human-readable shipping roadmap. The planner uses it as its primary input for task generation. Write it as a concrete plan with phases and steps:

```markdown
# my-tool — PyPI Publish

**Target**: First release on PyPI at version 0.1.0.

## Current state

Core functionality is implemented. Missing: packaging metadata, docs, CI.

## Phases

### Phase 1: Packaging
- Update pyproject.toml classifiers and project URLs
- Verify `uv build` produces a clean wheel

### Phase 2: Quality
- Add ruff linting; fix violations
- Add smoke tests for CI

### Phase 3: Release
- GitHub Actions for test-on-push and publish-on-tag
- Tag v0.1.0
```

---

## Notes

### The .dev/ convention

All autopilot working files live under `.dev/`. This directory should be in `.gitignore` — it contains orchestration state, not source code.

```
.dev/
├── sprint.md           # current task manifest
├── roadmap.md          # goal + validate definition
├── sprint-log.md       # sprint history (append-only)
├── project-summary.md  # researcher output
└── research/           # topic research reports
    └── {slug}/
        └── report.md
```

### Manifest evolution

`sprint.md` is a living document. You can:

- Add or edit tasks before they run
- Change `approved` back to `false` to re-run the judge
- Remove failed tasks or clear their metadata to retry
- Reorder tasks (dependencies are respected regardless of order)

Autopilot reads the manifest fresh on every run, so edits take effect immediately.
