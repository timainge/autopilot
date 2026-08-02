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

**All three loops are landed on `main`** (2026-08-02): Ralph (build),
Lisa (research), Frink (experiment). `.dev/plan.md` stages L0–L2 are
complete — see its §8 Progress log and §9 Decisions record. Default
smoke suite 26 green, fault suite 4 green, role-alignment, ast-lint,
ruff check+format, unit tests all green. Structural judge ALIGNED for
Lisa (×6) and Frink (×5 incl. #F1) under `.dev/logs/judge-pass/`.

Naming rule (plan.md §2): codenames only for self-driving loops
(`ralph`/`lisa`/`frink`); `homer`/`smithers` are retired
(`sprint execute` / `sprint prepare`). Ralph is demoted from headline to
supported build loop (kept for weaker/local models). Phase 3 (evals) and
Phase 4 (archetypes) were never planned in detail and are **not
scheduled** — see `.dev/vision-index.md` §Historical note. Next-up
candidates live in plan.md §9 "Known issues" (model threading for
non-frink roles is highest value).

---

## Authoritative Docs

Read in order. Each is canonical for its scope.

1. `.dev/vision-index.md` — reading-order router. **Start here.**
2. `.dev/plan.md` — the active execution plan: positioning, naming rule,
   stages L0–L2, merge gates.
3. `.dev/design.md` — implementation contract (incl. CLI surface and
   loop composition, §7).
4. `.dev/phase-5-lisa.md` — Lisa spec (implemented; landing).
5. `.dev/phase-5-frink.md` — Frink spec (landed; see its amendment block).
6. `.dev/phase-6-study.md` — Study spec (matrix validation runner — not
   a loop; frink develops, study validates).
7. `.dev/smoke-tests.md` — smoke + fault suites.
8. `.dev/duct-tape-frink-process.md` — manual Frink process; reference
   for known issues.
9. `.dev/backlog.md` — deferred one-liners; not plannable without
   promotion.

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
