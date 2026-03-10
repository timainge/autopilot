# Manifest Format

The manifest is the central artifact of autopilot. It lives at `.dev/autopilot.md` in your project root — a YAML-frontmatted markdown file with task checkboxes. It serves simultaneously as a project plan, a task spec, and a live state tracker.

---

## File Location

```
your-project/
└── .dev/
    └── autopilot.md   ← the manifest
```

Add `.dev/` to your `.gitignore` — autopilot working files are local state, not source code:

```gitignore
.dev/
```

---

## Frontmatter Fields

The file starts with a YAML frontmatter block between `---` delimiters:

```yaml
---
name: my-project
approved: false
status: active
max_budget_usd: 5.0
max_task_attempts: 3
---
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | directory name | Human-readable project name. Used in log output and session naming. |
| `approved` | bool | `false` | Whether the manifest is approved for worker execution. The judge phase sets this (or you set it manually). |
| `status` | string | `active` | Project lifecycle status. Values: `active`, `paused`, `done`, `in_progress`. Autopilot sets `in_progress` during a run. |
| `max_budget_usd` | float | `5.0` | Maximum total LLM spend (in USD) per autopilot run. Execution stops if this limit is reached. |
| `max_task_attempts` | int | `3` | How many times autopilot will retry a task before marking it `failed`. |

---

## Task Syntax

Tasks are H3 markdown headings with a checkbox:

```markdown
### [ ] task-id

Task description and instructions here. Any markdown is valid.

Include context, constraints, and a clear done criterion.

**Done**: A verifiable statement of what "complete" means.
```

### Task ID

The text after `[ ]` is the task ID — a short, lowercase, hyphen-separated slug. IDs must be unique within the manifest. Examples: `setup-linting`, `write-tests`, `deploy-staging`.

### Checkbox States

| Syntax | Meaning |
|--------|---------|
| `### [ ] task-id` | Pending — not yet started |
| `### [x] task-id` | Complete — the worker checked this box |

### Task Body

Everything between the heading and the next `---` separator (or next heading) is the task body. Write it as instructions for the worker agent. Be specific: include file names, commands to run, expected outputs.

Always include a `**Done**:` line with a verifiable criterion — the worker checks this to confirm the task is complete.

---

## Inline Metadata

Tasks can carry inline metadata tags appended to the heading line. These are written by autopilot during execution — you typically don't write them manually.

```markdown
### [ ] my-task [depends: other-task] [attempts: 2] [status: failed] [error: pytest returned exit code 1]
```

| Tag | Written by | Meaning |
|-----|-----------|---------|
| `[depends: task-id]` | You (the author) | This task cannot start until `task-id` is complete. Comma-separate multiple deps: `[depends: task-a, task-b]`. |
| `[attempts: N]` | Autopilot | Number of times this task has been attempted. |
| `[status: failed]` | Autopilot | Task failed after `max_task_attempts` retries. |
| `[error: ...]` | Autopilot | The last error message from a failed attempt. |

### Task Dependencies

Use `[depends: ...]` to declare ordering constraints:

```markdown
### [ ] write-tests [depends: setup-linting]
```

Tasks with unmet dependencies are skipped until their prerequisites are complete. On the next run, they become eligible.

---

## Full Annotated Example

```markdown
---
name: my-api
approved: true          # set to true after reviewing the judge's feedback
status: active
max_budget_usd: 8.0     # stop if total LLM cost exceeds $8
max_task_attempts: 3    # retry failing tasks up to 3 times
---

# My API — v1.0 Launch

## Context

A REST API built with FastAPI. This sprint adds authentication, writes tests,
and prepares the package for PyPI publication.

## Tasks

### [x] setup-auth

Add JWT-based authentication to the API. Install `python-jose` and
`passlib[bcrypt]`. Implement `/auth/login` and `/auth/me` endpoints.

**Done**: `pytest tests/test_auth.py -v` exits 0 with all tests passing.

---

### [ ] write-integration-tests [depends: setup-auth]

Write integration tests for all API endpoints using pytest and httpx.
Cover happy paths and error cases (401, 404, 422).

**Done**: `pytest tests/ -v` exits 0 with at least 20 tests passing;
coverage report shows >80% for `src/`.

---

### [ ] prepare-pypi [depends: write-integration-tests]

Update `pyproject.toml` with classifiers, keywords, and project URLs.
Run `uv build && uv run twine check dist/*`.

**Done**: `twine check dist/*` exits 0 with no warnings.
```

---

## Notes

### Separator Lines

Task entries are typically separated by `---` horizontal rules. These are optional but improve readability and help autopilot parse task boundaries cleanly.

### Manifest Evolution

The manifest is a living document. You can:

- Add new tasks at any time (they'll run on the next `autopilot .`)
- Edit task descriptions before they run
- Change `approved` back to `false` to re-run the judge
- Remove failed tasks or reset their metadata to retry them

Autopilot reads the manifest fresh on every run, so edits take effect immediately.
