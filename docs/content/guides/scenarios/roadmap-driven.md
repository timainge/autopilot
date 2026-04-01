# Roadmap-Driven Development

> Start from a goal, not a task list. Autopilot researches your project, builds a shipping roadmap, then plans and executes tasks to get there.

**When to use this:** You have a project that needs to ship — a library to publish, an API to launch, a tool to release — but you're not sure of all the steps. You want autopilot to assess where the project stands and chart a path to the goal.

---

## The workflow

```
project → roadmap → plan → sprint
```

### 1. Build the roadmap

```bash
autopilot roadmap .
```

The roadmap agent analyses your project (code, existing docs, git history) and writes `.dev/roadmap.md`. It determines:

- The right **goal type** (`launch`, `publish`, or `complete`)
- The appropriate **archetype** (e.g. `python-cli`, `web-api`) for bundled runbooks
- A concrete **shipping roadmap**: target, phases, and steps
- **Validate commands** — shell commands that must pass when the goal is met

For a deeper analysis with web search and ecosystem research:

```bash
autopilot roadmap --deep .
```

For a focused research question without producing a roadmap:

```bash
autopilot roadmap --topic "What's the right auth strategy for this app?" .
```

This writes a report to `.dev/research/{slug}/report.md`.

### 2. Review the roadmap

Open `.dev/roadmap.md`. The frontmatter tells autopilot what "done" looks like:

```yaml
---
goal: publish
archetype: python-cli
validate:
  - uv build
  - uv run twine check dist/*
  - pip install dist/*.whl && autopilot --version
---
```

The body is a human-readable shipping roadmap with phases and steps. Edit it if the goal or priorities need adjustment — this is your spec.

### 3. Plan from the roadmap

```bash
autopilot plan .
```

The planner reads `.dev/roadmap.md` as its primary input. If the roadmap exists, it skips the lazy research phase. It produces a `.dev/sprint.md` scoped to the current phase of the roadmap.

Review and approve the plan, then execute:

```bash
autopilot sprint .
```

### 4. Iterate

After the sprint, re-run `autopilot plan .` to plan the next phase. The planner reads the sprint log (`.dev/sprint-log.md`) as context, so it knows what's already been done.

For fully autonomous iteration, see [Ralph](ralph.md).

---

## Example roadmap

After `autopilot roadmap .` on a Python CLI tool:

```markdown
---
goal: publish
archetype: python-cli
validate:
  - uv build
  - uv run twine check dist/*
  - pip install --dry-run dist/*.whl
---

# my-tool — PyPI Publish

**Target**: First public release on PyPI at version 0.1.0.

## Current state

The core functionality is implemented. Missing: proper packaging metadata,
documentation, and a CI pipeline for automated releases.

## Phases

### Phase 1: Packaging and metadata
- Update `pyproject.toml` with classifiers, keywords, and project URLs
- Add `README.md` with install instructions and basic usage
- Configure `uv build` and verify the wheel is clean

### Phase 2: Quality gates
- Add `ruff` for linting; fix existing violations
- Write smoke tests that can run in CI
- Configure `pytest` in `pyproject.toml`

### Phase 3: CI and release
- Add GitHub Actions workflow: test on push, publish on tag
- Tag v0.1.0 and verify the release pipeline
```

---

## Topic research

If you're unsure about a specific technical decision, use `--topic` to get a focused research report before committing to a roadmap:

```bash
autopilot roadmap --topic "Should this be a FastAPI app or a serverless function?" .
autopilot roadmap --topic-file research-brief.md .
```

The report lands in `.dev/research/{slug}/report.md`. Read it, then run `autopilot roadmap .` to produce the actual roadmap with that context in mind.

---

## Next steps

For fully autonomous development — no manual planning steps — see [Ralph: Autonomous Loop](ralph.md).
