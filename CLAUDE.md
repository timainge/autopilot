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

Phases 1 + 2 complete and merged to `main`. Domain model refactor, CLI
atomic commands, structural judge pass (all seven code-facing principles
ALIGNED), and role-alignment lint are all landed. Smoke (S1–S5 + A01–A10),
fault (F1–F3), role-alignment, and ast-lint suites are green.

Active work: `.dev/phase-3-evals.md` (signal floor — driven by the
notes-app real-smoke dossier). Phase 4 (archetypes) and Phase 5 (Lisa +
Frink + additional domain models) follow. `.dev/phase-2.md` is retained
as a historical record of the merge-gate work.

---

## Authoritative Docs

Read in order. Each is canonical for its scope.

1. `.dev/vision-index.md` — reading-order router over the consolidated
   topic files. **Start here.** Most entries currently carry a
   `[FOR APPROVAL]` marker pending a review pass on the April 2026
   consolidation.
2. `.dev/design.md` — implementation contract.
3. `.dev/workflows.md` — CLI surface, entity lifecycle, loop composition.
4. `.dev/smoke-tests.md` — tests the Phase 1 refactor passed to merge.
5. `.dev/phase-3-evals.md` — **active**: signal floor (goal-sanity rubrics,
   sprint inspection, scope-drift eval).
6. `.dev/phase-4-archetypes.md` — next after Phase 3.
7. `.dev/phase-5-lisa.md` / `.dev/phase-5-frink.md` /
   `.dev/phase-5-additional-domain-models.md` — outer loops +
   optional knowledge-entity domain.
8. `.dev/backlog.md` — deferred one-liners; not plannable without
   promotion.
9. `.dev/phase-2.md` — historical record of the merge-gate work; do not
   reopen, do not plan from.

Undocumented design decisions are a bug. If the docs are unclear, ask or
update them — do not guess. Never plan from an archived doc under
`.archive/.dev/`; the consolidated topic files above are the source of
truth.

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
tests/smoke/run.sh                      # default suite (S1–S5, A01–A10, role-alignment, ast-lint)
tests/smoke/run.sh fault                # fault injection (F1–F3)
uv run pytest tests/                    # serialization-boundary unit tests (e.g. ref parser)
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

- `main` is authoritative. Feature branches off `main`.
- Merge gate for any branch back to `main`: full smoke suite green, fault
  suite green, role-alignment lint green, ruff clean. Structural judge
  re-run required only when changes touch principle-bearing surfaces
  (persistence, mutation, config tunables, role files).

---

## When In Doubt

Ask. The cost of a clarifying question is small; the cost of a guess that
encodes the wrong assumption is large. Pause and check rather than
proceeding on an unstated assumption — especially when the design docs are
silent, or when archive behaviour seems to conflict with the target.
