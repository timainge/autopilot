# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

---

## Refactor Mode Active

Phase 1 domain model refactor is in progress on branch `phase-1-refactor`. The package
at `src/autopilot/` is being rebuilt from scratch. Old code lives at
`.archive/autopilot/` and is **reference-only**.

### No Backwards Compatibility

Existing field names, file formats, CLI flags, and APIs are **not constraints**. Breaking
changes are the default, not the exception.

- Do not write migration shims, compatibility wrappers, or deprecation paths.
- Do not preserve an abstraction because "existing projects might depend on it."
- Do not keep a field name, file layout, or CLI flag out of loyalty to the archived
  implementation. If the old shape is wrong, break it.

If preservation is ever the right call, `.dev/phase-1-design.md §9 Feature Parity Matrix`
flags it explicitly. Absence from that matrix = nothing to preserve.

### Greenfield Discipline

`.archive/` is reference-only.

- **Do not import from it.** `from autopilot.archive...` is forbidden. The firewall is
  physical: `.archive/` is outside the Python package path.
- **Do not copy patterns from it.** Read `.dev/vision.md` and `.dev/phase-1-design.md` to
  understand the target. Consult `.archive/` only to answer specific behavioural
  questions the docs don't cover — and then state the question, not the conclusion.
- **Do not treat it as a fallback.** If the design doc is unclear, ask or update the
  design doc. Do not silently fall back to "do what the old code did."

### Authoritative Docs

Read in order:

1. `.dev/vision-index.md` — routing document. Start here for the reading order.
2. `.dev/phase-1-design.md` — implementation design. **The contract.**
3. `.dev/vision.md` — design intent.
4. `.dev/vision-testing.md` — correctness layers.
5. `.dev/phase-1-smoke-tests.md` — the tests the refactor must pass to merge.

All Phase 1 work derives from these. No undocumented design decisions.

---

## Project Overview

Autopilot is an autonomous project session orchestrator for Claude Code. It reads a
project's roadmap, plans a sprint against the next goal, executes the sprint through the
Anthropic Agent SDK, and loops until goals are achieved. The filesystem under `.dev/` is
live, ambient state: it reflects what is planned, in progress, succeeded, or failed at
any moment.

Domain hierarchy: `Roadmap → Goals → Sprints → Tasks`. Full model in `phase-1-design.md`.

---

## Development Commands

The CLI surface is in flux during the refactor. Target shape is documented in
`phase-1-design.md §3 Scope`. During rebuild, the package may not install or run at all —
this is expected.

Always-useful commands:

```bash
uv pip install -e .                 # editable install (will error until new cli is built)
uv run ruff check src/              # lint
uv run ruff format --check src/     # format check
tests/smoke/run.sh                  # smoke tests (after phase-1-smoke-tests.md is implemented)
```

The smoke tests are the primary correctness signal (per `vision-testing.md`). Unit tests
have a small, narrow role at the serialization boundary — do not drive the refactor
from them.

---

## Code Style

- Python 3.11+, async/await throughout
- Ruff: line length 100, rules `E, F, I, N, W, UP`
- Dataclasses (not Pydantic)
- Type hints with `X | None` union syntax (not `Optional`)
- No docstrings on trivial methods; one-line docstrings on non-obvious ones. No
  multi-paragraph docstrings. Comments are for WHY-non-obvious only.
- Active record: entities own their persistence via `@persists`. No free-function
  `save_task(task)`. No separate repository layer.
- Validate on mutate: invariants in constructors and mutation methods. No separate
  `validate()` methods. No fixup passes.

---

## Branch Strategy

- Refactor work: `phase-1-refactor` branch.
- Main stays shippable from `src/autopilot/` as it was pre-refactor (via the archive if
  a hotfix is needed — but v0.2.x releases from main should not require touching the
  archive).
- Merge gate: smoke tests green + fault injection passes + structural judge finds no
  divergence from `phase-1-design.md`.

---

## When In Doubt

Ask. The cost of a clarifying question is small; the cost of a guess that encodes the
wrong assumption across the refactor is large. Prefer pausing to check over proceeding
with unstated assumptions — especially when the design doc is silent on a specific
decision, or when archived behaviour seems to conflict with the target design.
