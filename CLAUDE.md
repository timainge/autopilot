# CLAUDE.md

Guidance for Claude Code working in this repository.

---

## Project Overview

Autopilot is an autonomous project session orchestrator for Claude Code. It
reads a project's roadmap, plans a sprint against the next goal, executes the
sprint through the Claude Agent SDK, and loops until goals are achieved. The
filesystem under `.dev/` is live, ambient state: it reflects what is planned,
in progress, succeeded, or failed at any moment.

Domain hierarchy: `Roadmap → Goals → Sprints → Tasks`. Full model in
`design.md`.

---

## Status

Phase 1 (domain model refactor) is implementation-complete. Smoke + fault
suites green. Phase 2 closes remaining gaps (structural judge pass, CLI
atomic commands, role alignment) before `phase-1-refactor` merges to `main`.
See `.dev/phase-2.md` for active work, `.dev/phase-3.md` for deferred
directions.

---

## Authoritative Docs

Read in order. Each is canonical for its scope.

1. `.dev/vision-index.md` — reading-order router. Start here.
2. `.dev/design.md` — implementation design. The contract.
3. `.dev/workflows.md` — CLI surface, entity lifecycle, loop composition.
4. `.dev/vision.md` — authoritative design intent.
5. `.dev/vision-testing.md` — the three correctness layers (smoke / fault /
   judge).
6. `.dev/smoke-tests.md` — the tests the refactor passed to merge.
7. `.dev/phase-2.md` — active next-steps.
8. `.dev/phase-3.md` — deferred directions; do not ship from this doc.

Undocumented design decisions are a bug. If the docs are unclear, ask or
update them — do not guess.

---

## Archive Policy

`.archive/autopilot/` holds the pre-refactor implementation and is
**reference-only**.

- Do not import from it. `from autopilot.archive...` is forbidden — the
  firewall is physical (archive is outside the package path).
- Do not copy patterns from it. Read the authoritative docs to understand
  the target. Consult `.archive/` only to answer a specific behavioural
  question the docs don't cover — and state the question, not the
  conclusion.
- Do not treat it as a fallback. If a design doc is silent, ask or edit
  the doc.

---

## Forward-Change Posture

No backwards compatibility constraints today. Breaking changes are the
default until there's a first external user — none yet.

- No migration shims, no compatibility wrappers, no deprecation paths.
- Do not preserve a field name / file layout / CLI flag out of loyalty to
  any prior shape. If it's wrong, break it.
- Once a first external user exists, breaking changes go in release notes
  with a minor-version bump. Still no shims.

---

## Development Commands

```bash
uv pip install -e .                     # editable install
uv run autopilot --help                 # smoke the CLI
uv run ruff check src/                  # lint
uv run ruff format --check src/         # format check
tests/smoke/run.sh                      # default smoke suite (S1–S5 + lint)
tests/smoke/run.sh fault                # fault injection (F1–F3)
```

Smoke tests are the primary correctness signal (per `vision-testing.md`).
Unit tests have a small, narrow role at the serialization boundary — do not
drive design from them.

---

## Code Style

- Python 3.11+, async/await throughout.
- Ruff: line length 100, rules `E, F, I, N, W, UP`.
- Dataclasses (not Pydantic).
- Type hints with `X | None` union syntax (not `Optional`).
- No docstrings on trivial methods. One-line docstrings on non-obvious
  ones. No multi-paragraph docstrings. Comments are for WHY-non-obvious
  only.
- Active record: entities own their persistence via `@persists`. No free-
  function `save_task(task)`. No repository layer.
- Validate on mutate: invariants in `__post_init__` and mutation methods.
  No separate `validate()`. No fixup passes.
- Tunables live in `AutopilotConfig` (see `design.md §12.13`). Literals in
  call sites are bugs.
- Paths are `pathlib.Path`. File I/O specifies `encoding="utf-8"`.

---

## Branch Strategy

- Active work: `phase-1-refactor` (pending Phase 2 completion + merge to
  `main`).
- After merge: `main` is authoritative; feature branches off `main`.
- Merge gate to `main`: `phase-2.md §3` — smoke green, fault green,
  structural judge ALIGNED on all principles, CLI atomics complete, role
  alignment lint green.

---

## When In Doubt

Ask. The cost of a clarifying question is small; the cost of a guess that
encodes the wrong assumption is large. Pause and check rather than
proceeding on an unstated assumption — especially when the design docs are
silent, or when archive behaviour seems to conflict with the target.
