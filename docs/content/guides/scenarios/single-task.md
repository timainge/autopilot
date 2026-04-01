# Single Task

> Run one specific task without a roadmap or full planning cycle. The fastest path to getting something done.

**When to use this:** You have a specific, well-defined task — fix this bug, add this endpoint, update this config — and you want Claude Code to just do it.

---

## The pattern

Write a single task in `.dev/sprint.md` and run `autopilot sprint --auto-approve .`.

```bash
mkdir -p .dev
```

```markdown title=".dev/sprint.md"
---
name: my-project
approved: true
max_budget_usd: 2.0
---

### [ ] fix-import-error

The import at `src/app/utils.py:12` fails because `requests` is not listed
in `pyproject.toml` dependencies. Add it and verify:

```bash
uv add requests
uv run python -c "from app.utils import fetch_data; print('ok')"
```

**Done**: the import succeeds and `uv run pytest tests/test_utils.py` passes.
```

Execute:

```bash
autopilot sprint --auto-approve .
```

The `--auto-approve` flag bypasses the manual approval check since you've already set `approved: true` in the frontmatter.

---

## Task writing tips

The worker agent only knows what you put in the task body. Good tasks include:

- **Exact file paths** — `src/app/models.py`, not "the models file"
- **Commands to run** — so the worker can verify the work
- **A `**Done**:` criterion** — a clear, verifiable statement of what "complete" looks like

```markdown
### [ ] add-health-endpoint

Add a `GET /health` endpoint to `src/api/routes.py` that returns
`{"status": "ok", "version": "1.0"}` as JSON.

Register it on the FastAPI app in `src/api/app.py`.

**Done**: `curl http://localhost:8000/health` returns `{"status":"ok","version":"1.0"}`.
```

---

## Budget and retries

For a single task, a budget of `$1–3` is usually plenty. Set `max_task_attempts: 1` if you don't want retries:

```yaml
---
approved: true
max_budget_usd: 2.0
max_task_attempts: 1
---
```

---

## Checking the session

Every task spawns a Claude Code session named `autopilot/<project>/worker`. After a run, you can resume it from Claude Code's session history with `/resume` to see exactly what happened.

---

## Next steps

For more complex work, see [Plan & Sprint](plan-and-sprint.md) — let autopilot break the work into tasks for you.
