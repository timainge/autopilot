---
phase: 6
title: Add ralph command (outer loop)
status: done
depends: task-005
priority: medium
---

# Task 006: Add ralph Command (outer loop)

## Summary

Ralph is the outer loop: `(plan → sprint → evaluate) × N until GOAL_MET or stuck`.

Ralph replaces the old `sprint --loop` / `sprint --auto` looping behavior. It's a clean rewrite, not a refactor of `sprint_project()`. After Phase 6:
- `sprint_project()` can be deleted (its logic is superseded by plan + execute_sprint + evaluate_project + ralph_project)
- `ralph` is the new long-running autonomous command

---

## Current sprint_project() — What Ralph Absorbs

`sprint_project()` (orchestrator.py lines 573-884) does:
1. Load strategy/roadmap manifest, runbook, sprint log (→ ralph does this from roadmap.md)
2. Determine validation commands (from roadmap.md `validate:` after Phase 2)
3. Sprint loop:
   a. Check max_sprints
   b. Run planner in sprint mode (writes sprint.md)
   c. Run critic (optional)
   d. Load sprint plan, run judge (approval gate)
   e. Execute task loop (workers)
   f. Run validation hooks
   g. Remediation loop if validation fails (re-plan, re-execute, re-validate up to 2x)
   h. Run evaluator (STRATEGY_SATISFIED → GOAL_MET after Phase 2)
   i. Append sprint log
   j. If satisfied or not looping: break; else increment sprint_number

Ralph absorbs steps 1-j but as clean separate calls to:
- `plan_project()` (handles planner + critic + judge internally, writes approved sprint.md)
- `execute_sprint()` (worker loop, returns task counts)
- `run_validation_hooks()` (validate commands from roadmap.md)
- `evaluate_project()` (from Phase 2, reads roadmap.md + sprint log → GOAL_MET)

The remediation sub-loop in sprint_project() (steps 13/f-g) is tricky: after Phase 5, plan_project() already does planner → critic → judge. But remediation-after-validation-failure is different: it's "re-plan given that validation failed". In ralph_project(), if validation fails after execute_sprint(), we can call plan_project() again with the validation output as context (passing it as a judge_feedback-like parameter).

**Simplification for Phase 6**: Don't implement remediation in ralph. If validation fails, log it, append to sprint log, let evaluate_project() decide GOAL_MET (it will say NO), and continue the loop. This is simpler and the outer loop naturally handles it.

---

## ralph_project() Implementation

```python
async def ralph_project(
    project_path: Path,
    agents_dir: Path,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Outer loop: plan → sprint → evaluate until GOAL_MET or stuck."""
    if cfg is None:
        cfg = load_config(project_path)

    project_name = project_path.name

    # Require roadmap.md
    if not cfg.roadmap_path(project_path).exists():
        log(project_name, "No .dev/roadmap.md found — run 'autopilot roadmap .' first", "❌")
        return

    # Load validation commands from roadmap.md frontmatter
    roadmap_text = load_roadmap_text(project_path, cfg)
    # Parse validation commands from roadmap frontmatter (need parse_frontmatter)
    roadmap_fm, _ = parse_frontmatter(roadmap_text)
    validation_commands: list[str] = roadmap_fm.get("validate", [])
    # Also check archetypes index for default validate commands
    archetypes_index = load_archetypes_index(cfg)
    archetype = roadmap_fm.get("archetype")
    if not validation_commands and archetypes_index and archetype:
        for entry in archetypes_index:
            if entry.get("name") == archetype:
                validation_commands = entry.get("validate", [])
                break

    sprint_log = load_sprint_log(project_path, cfg)
    sprint_number = sprint_log.count("## Sprint") + 1

    while True:
        # Check max_sprints
        if sprint_number > cfg.max_sprints:
            log(project_name, f"Reached max_sprints ({cfg.max_sprints}) — stopping", "🛑")
            break

        log(project_name, f"=== Ralph Sprint {sprint_number} ===", "🔄")

        # Plan (internal: planner → critic → judge → approved sprint.md)
        log(project_name, f"Sprint {sprint_number}: Planning...", "📝")
        await plan_project(project_path, agents_dir, cfg=cfg)

        # Check that plan succeeded and is approved
        sprint_manifest = load_sprint_plan(project_path, cfg)
        if sprint_manifest is None or not sprint_manifest.approved:
            log(project_name, "Plan not approved after planning — stopping ralph", "❌")
            break

        # Execute sprint
        log(project_name, f"Sprint {sprint_number}: Executing...", "🔧")
        tasks_planned, tasks_completed, tasks_failed = await execute_sprint(
            project_path, agents_dir, cfg=cfg
        )

        # Stuck detection: if tasks failed, plant deferred task in roadmap.md
        if tasks_failed > 0:
            log(project_name, f"Sprint {sprint_number}: {tasks_failed} task(s) failed — stopping", "🛑")
            _append_deferred_to_roadmap(project_path, cfg, sprint_number, tasks_failed)
            break

        # Validate
        validation_passed, validation_output = await run_validation_hooks(
            project_path, validation_commands
        )
        if not validation_passed:
            log(project_name, f"Sprint {sprint_number}: Validation failed", "⚠️")

        # Evaluate
        goal_met, assessment = await evaluate_project(project_path, agents_dir, cfg=cfg)

        # Append sprint log
        total_cost = 0.0  # TODO: accumulate from execute_sprint return value in later cleanup
        sr = SprintResult(
            sprint_number=sprint_number,
            tasks_planned=tasks_planned,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            validation_passed=validation_passed,
            evaluation=assessment,
            strategy_satisfied=goal_met,  # field rename deferred
            cost_usd=total_cost,
        )
        append_sprint_log(project_path, sr, cfg)
        sprint_log = load_sprint_log(project_path, cfg)

        if goal_met:
            log(project_name, f"Sprint {sprint_number}: GOAL MET 🎉", "✅")
            break

        log(project_name, f"Sprint {sprint_number}: Not done — continuing", "🔄")
        sprint_number += 1
```

### _append_deferred_to_roadmap() helper

```python
def _append_deferred_to_roadmap(project_path, cfg, sprint_number, tasks_failed) -> None:
    """Append a deferred investigation task to roadmap.md."""
    roadmap_path = cfg.roadmap_path(project_path)
    if not roadmap_path.exists():
        return
    deferred_section = (
        f"\n## Deferred (Sprint {sprint_number})\n\n"
        f"- [ ] Investigate why {tasks_failed} task(s) failed in sprint {sprint_number} — "
        f"consider re-planning or re-roadmapping before next ralph run\n"
    )
    with roadmap_path.open("a", encoding="utf-8") as f:
        f.write(deferred_section)
```

This lives in `orchestrator.py` as a private helper (or in manifest.py as a public function).

---

## Cost tracking improvement (deferred)

The `execute_sprint()` currently returns `(tasks_planned, tasks_completed, tasks_failed)`. To get cost, it should also return total_cost. But that requires threading cost through the worker loop. Defer this — for Phase 6, SprintResult.cost_usd = 0.0 in ralph (the per-sprint cost logging still works inside execute_sprint).

---

## Delete sprint_project()

After ralph_project() is working:
- `sprint_project()` is superseded
- Delete from orchestrator.py
- Remove from cli.py imports (it was already un-wired in Phase 4)

The old `sprint --auto` / `sprint --loop` behavior is replaced by `ralph`. Users who were using `sprint --auto` should migrate to `ralph`.

---

## CLI Changes

### Add ralph subparser

```python
ralph_p = subparsers.add_parser("ralph", help="Outer loop: plan → sprint → evaluate until goal met")
_add_common(ralph_p)
ralph_p.add_argument(
    "--auto-approve",
    action="store_true",
    help="Automatically approve sprint plans without human review",
)
```

Note: ralph has `auto_approve` but no `--loop` (it's always a loop). The only stop conditions are: GOAL_MET, max_sprints, or stuck (task failures).

### Update SUBCOMMANDS

Add `"ralph"` to SUBCOMMANDS set.

### Add case "ralph": to match block

```python
case "ralph":
    await ralph_project(
        project_path, agents_dir,
        auto_approve=args.auto_approve,
        cfg=cfg,
    )
```

### broad set

`ralph` is not a "broad" command (it needs roadmap.md, not just any project dir). But it should fall back to cwd if no path given. Add to the cwd fallback section: ralph needs roadmap.md, so use same pattern as sprint.

---

## plan_project() sprint-mode context

Inside ralph, `plan_project()` is called on every iteration. The planner needs to see:
- roadmap.md (already in cwd, planner reads it)
- sprint-log.md (already in cwd, planner reads it)

The current `plan_project()` doesn't explicitly pass sprint_log to the planner prompt — but the planner agent's system prompt should instruct it to read sprint-log.md if present.

**Check**: `build_planner_prompt()` in non-sprint-mode does NOT include sprint log. The planner agent's system prompt (`agents/planner.md`) may or may not read sprint-log.md automatically.

**Fix**: Update `build_planner_prompt()` to optionally include sprint_log:
```python
def build_planner_prompt(project_path, context_file=None, sprint_log="", judge_feedback="") -> str:
```

But the planner agent running via plan_project() should read sprint-log.md itself (it has file access). The design intent is that the planner reads what it needs from the project. Let the planner's system prompt instruct it to read sprint-log.md if present, and trust it to do so.

**Decision**: Don't pass sprint_log inline to plan_project(). Update the planner system prompt to always check for and read sprint-log.md. This is simpler.

---

## sprint_project() vs ralph_project() — key differences

| | sprint_project() | ralph_project() |
|---|---|---|
| Loads strategy.md | Yes (deleted in Phase 2) | No |
| Calls planner directly | Yes (sprint mode) | Via plan_project() |
| Internal remediation loop | Yes (2 retries) | No (loop handles it) |
| Evaluation | strategist agent | evaluate_project() (roadmap agent) |
| Loop control | auto_loop flag | always loops |
| Stuck handling | just logs | appends deferred task to roadmap.md |

---

## Implementation Steps

### Step 6.1 — Add ralph_project() to orchestrator.py

- [x] Implement `ralph_project()` as above
- [x] Implement `append_deferred_to_roadmap()` helper (in manifest.py)
- [x] Import `parse_frontmatter` in orchestrator.py (from manifest) for roadmap frontmatter parsing
- [x] Import `SprintResult` from models (already imported)

### Step 6.2 — Update planner agent system prompt

- [x] Read `agents/planner.md` — check if it reads sprint-log.md
- [x] Add instruction to check for and read `.dev/sprint-log.md` if it exists (already present)
- [x] Add instruction to check for and read `.dev/roadmap.md` (already present)

### Step 6.3 — Add ralph CLI subcommand

- [x] Add `ralph_p` subparser to cli.py
- [x] Add `"ralph"` to SUBCOMMANDS set
- [x] Add `ralph_project` to orchestrator imports
- [x] Add `case "ralph":` match block

### Step 6.4 — Delete sprint_project()

- [x] Confirm ralph_project() covers the use cases
- [x] Delete `sprint_project()` from orchestrator.py
- [x] Remove from any remaining imports

### Step 6.5 — SprintResult field rename (optional cleanup)

- [x] `SprintResult.strategy_satisfied` → `SprintResult.goal_met`
- [x] Update `append_sprint_log()` in manifest.py (line 475: uses `strategy_satisfied`)
- [x] Update all usages in ralph_project(), evaluate_project()

### Step 6.6 — Documentation

- [x] `CLAUDE.md`: add ralph to commands table, remove sprint --loop reference
- [x] `README.md`: add ralph usage section

---

## Verification Checklist

- [ ] `autopilot ralph .` → requires roadmap.md, loops plan→sprint→evaluate until GOAL_MET
- [ ] `autopilot ralph .` with task failures → appends deferred task to roadmap.md, stops
- [ ] `autopilot ralph .` without roadmap.md → clear error message
- [ ] `autopilot sprint --auto .` → "unknown flag" (or just removed)
- [ ] `grep -r "sprint_project" src/` → zero hits
- [ ] `ruff check src/` passes
