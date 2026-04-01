# Plan & Sprint

> Give autopilot some context, let it build a task plan, review it, then execute. The bread-and-butter workflow for structured feature work.

**When to use this:** You have a feature, refactor, or fix that's too big for a single task, but you know roughly what needs doing. You want autopilot to break it into clean, sequenced tasks — but you want to review the plan before anything runs.

---

## The workflow

```
context (optional) → plan → review → approve → sprint
```

### 1. Prepare context (optional)

You can seed the planner with any file — a TODO list, a design doc, a spec, or just a rough brief:

```markdown title="brief.md"
## Goal

Add JWT authentication to the FastAPI app.

## Requirements

- POST /auth/login — accepts email/password, returns JWT
- GET /auth/me — requires valid JWT, returns current user
- Middleware to protect existing routes
- Tests for both endpoints

## Notes

Using python-jose for JWT, passlib for password hashing.
Existing user model is in src/models/user.py.
```

### 2. Run the planner

```bash
# With a context file (skips lazy research)
autopilot plan --context brief.md .

# Without context (autopilot researches the project first)
autopilot plan .
```

The planner writes `.dev/sprint.md`. A critic agent reviews it automatically (if configured), then a judge evaluates readiness. If the judge approves, `approved: true` is set.

### 3. Review the plan

Open `.dev/sprint.md` and read through the tasks. Things to check:

- Are the tasks in the right order?
- Is anything missing or over-specified?
- Do the done criteria make sense?

You can edit tasks freely — add context, fix file paths, adjust scope, reorder with dependencies.

### 4. Execute

```bash
autopilot sprint .
```

If `approved: true` is already set (judge approved it), this runs immediately. If `approved: false`, set it to `true` first or pass `--auto-approve`:

```bash
autopilot sprint --auto-approve .
```

---

## Example manifest

After `autopilot plan --context brief.md .`, your `.dev/sprint.md` might look like:

```markdown
---
name: my-api
approved: true
max_budget_usd: 8.0
max_task_attempts: 3
---

### [ ] install-auth-deps

Install `python-jose[cryptography]` and `passlib[bcrypt]` via uv.
Add them to `pyproject.toml` dependencies.

**Done**: `uv run python -c "import jose, passlib"` exits 0.

---

### [ ] implement-login [depends: install-auth-deps]

Add `POST /auth/login` endpoint in `src/api/routes/auth.py`.
Accept `{"email": str, "password": str}`, validate against user model,
return `{"access_token": str, "token_type": "bearer"}` on success,
401 on failure.

**Done**: `pytest tests/test_auth.py::test_login` passes.

---

### [ ] implement-me-endpoint [depends: implement-login]

Add `GET /auth/me` endpoint. Require a valid Bearer token via
`get_current_user` dependency. Return the serialized user object.

**Done**: `pytest tests/test_auth.py::test_me_authenticated` passes.
```

---

## Using `build` for one-shot

If you trust the planner and don't need to review, `build` combines plan + sprint in one command:

```bash
autopilot build --context brief.md .
```

Equivalent to `autopilot plan --context brief.md . && autopilot sprint --auto-approve .`.

---

## Recovering from failures

If a task fails after `max_task_attempts` retries, it's marked `[status: failed]` in the manifest. Fix the task description or the underlying issue, then resume:

```bash
autopilot sprint --resume .
```

`--resume` resets the stuck/failed task status and retries.

---

## Next steps

For goal-oriented work where the tasks themselves need to be discovered, see [Roadmap-Driven Development](roadmap-driven.md).
