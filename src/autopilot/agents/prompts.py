"""Prompt builders per design §8. Accept entities, not dicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from autopilot.domain.clock import now
from autopilot.domain.experiment import Experiment, Lap
from autopilot.domain.goal import Goal
from autopilot.domain.research import Enquiry, ResearchRun
from autopilot.domain.roadmap import Roadmap
from autopilot.domain.sprint import Sprint
from autopilot.domain.task import AttemptRecord, Task

# How much task-intent text to include in prompt summary lines.
_INTENT_SNIPPET_CHARS = 120


def _workspace_preamble(cwd: Path, archetype: str | None = None) -> str:
    """Workspace grounding for an agent — runtime-aware.

    Tells the agent where it is on disk, what date it is, what archetype
    the project belongs to (when known), and constrains shell file
    discovery to the project tree. Solves the failure mode observed in
    cadence-smoke-run1 where a worker ran `find /` from filesystem root
    and hung 14+ minutes scanning Spotlight + /System.

    The SDK already sets the subprocess cwd correctly; this preamble
    surfaces that fact to the agent's prompt, which is what the model
    actually reads.
    """
    today = now().date().isoformat()
    archetype_line = f"Archetype: {archetype}\n" if archetype else ""
    return (
        "## Workspace\n\n"
        f"Working directory: `{cwd}`\n"
        "This is the project root — every relative path resolves from here.\n"
        f"Today's date: {today}\n"
        f"{archetype_line}"
        "\n"
        "Stay inside this directory. Use `Glob` for file discovery (e.g. "
        "`**/*.py`); if you must use shell `find`, scope it to `.` (e.g. "
        "`find . -path '*/main.py'`). Never search `/`, `/System`, "
        "`/Applications`, or absolute paths outside the project — those "
        "scans take minutes on macOS / Linux (Spotlight, network mounts) "
        "and will time the sprint out."
    )


# Task scope integrity — verbatim from `.dev/vision.md §Task Scope Integrity`.
# This is prompt-level protection (permission-level backstop is a follow-up).
_TASK_SCOPE_INTEGRITY = """\
## Task Scope Integrity

- The task file defines the work — you are executing against it, not authoring it.
- Done means done per the stated criterion — producing more than the DoD asks
  violates it, it does not satisfy it faster.
- Write scope is the project source files; task files, sprint files, and the
  roadmap are off-limits. Anything under `.dev/` that represents domain state is
  orchestrator-owned. Your entire concern is the codebase being built.
"""


def _fence(label: str, content: str) -> str:
    """Framed block with start/end sentinels — easy for the model to attend to."""
    return f"--- {label} START ---\n{content}\n--- {label} END ---"


def build_worker_prompt(
    task: Task,
    sprint: Sprint,
    prior_attempts: list[AttemptRecord],
    cwd: Path,
    archetype: str | None = None,
) -> str:
    """Worker prompt: workspace grounding + task intent + sprint context +
    task scope integrity + prior errors.

    Per design §9: retry prompt format (multi-line with blank separator) is preserved
    from the archived implementation.
    """
    sections: list[str] = [
        _workspace_preamble(cwd, archetype=archetype),
        "",
        "You are executing a single task from the current sprint.",
        "",
        f"Sprint: {sprint.id} (primary goal: {sprint.primary_goal})",
        f"Task: {task.id}",
        "",
        _fence("SPRINT CONTEXT", sprint.context),
        "",
        _fence("TASK INTENT", task.intent.strip()),
    ]

    if prior_attempts:
        errors = [a.error for a in prior_attempts if a.error]
        if errors:
            retry_block_parts: list[str] = []
            for i, err in enumerate(errors, start=1):
                retry_block_parts.append(
                    f"IMPORTANT — RETRY ATTEMPT {i + 1}:\n"
                    f"The previous attempt failed with this error:\n"
                    f"{err}\n\n"
                    f"Address this failure specifically before proceeding."
                )
            sections += ["", _fence("PREVIOUS ATTEMPT ERRORS", "\n\n".join(retry_block_parts))]

    sections += ["", _TASK_SCOPE_INTEGRITY]
    sections += [
        "",
        "When done, emit a one-line summary prefixed `SUMMARY:` that describes what",
        "you accomplished. The orchestrator reads this line to record the task summary.",
    ]
    return "\n".join(sections)


def _goal_yaml(goal: Goal) -> str:
    data = {
        "id": goal.id,
        "priority": goal.priority,
        "status": goal.status,
    }
    if goal.summary:
        data["summary"] = goal.summary
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _prior_sprint_summary(sprint: Sprint) -> str:
    line = f"- {sprint.id} [{sprint.status}] (goal={sprint.primary_goal})"
    if sprint.summary:
        line += f": {sprint.summary}"
    return line


_PLANNER_OUTPUT_CONTRACT = """\
OUTPUT CONTRACT — strict. The orchestrator parses your response text by
splitting on `### FILE:` headers. Do not write to disk; return one response
containing one sprint block and one block per task.

Format (exact):

    ### FILE: sprint-NNN.md
    ---
    id: sprint-NNN
    primary_goal: <goal-id>
    status: planning
    ---

    # Sprint NNN — <title>

    ## Context
    <prose>

    ## Tasks
    - [001](task-001.md): <summary>
    - [002](task-002.md): <summary>

    ### FILE: task-001.md
    ---
    id: '001'
    depends_on: []
    status: pending
    eval: []
    attempts: []
    summary: null
    ---

    # <task title>
    <prose + Done: + optional Watch:>

    ### FILE: task-002.md
    ...

Rules:
- Exactly one `sprint-NNN.md` block; the parser keys on that filename.
- One `task-NNN.md` block per task, filenames zero-padded three digits.
- Every frontmatter field above is required. Unknown fields are rejected.
- No prose or code fences outside the blocks. No leading preamble. The
  parser splits strictly on the `### FILE:` line."""


def build_planner_prompt(
    roadmap: Roadmap,
    goal: Goal,
    prior_sprints: list[Sprint],
    analysis: str | None,
    feedback: str | None = None,
    evaluator_feedback: str | None = None,
) -> str:
    """Planner prompt: roadmap narrative + goal + prior sprints + analysis + feedback.

    Output is parsed into Sprint/Task entities by `_parse_planner_output` (plan.py):
    the prompt specifies the `### FILE:` envelope contract literally so the model
    cannot drift onto a side-writes-files interpretation.

    `evaluator_feedback` is the prior sprint evaluator's prose verdict when an
    earlier sprint completed but the goal was judged not yet met — surfaced
    so this remediation sprint can address what the evaluator flagged.
    """
    sections: list[str] = [
        "Plan the next sprint against the target goal below.",
        "",
        f"Archetype: {roadmap.archetype}",
        "",
        _fence("ROADMAP NARRATIVE", roadmap.narrative.strip()),
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
    ]

    if prior_sprints:
        summary_lines = [_prior_sprint_summary(s) for s in prior_sprints]
        sections += ["", _fence("PRIOR SPRINTS", "\n".join(summary_lines))]

    if evaluator_feedback:
        sections += ["", _fence("PRIOR EVALUATOR FEEDBACK", evaluator_feedback.strip())]

    if analysis:
        sections += ["", _fence("PROJECT ANALYSIS", analysis.strip())]

    if feedback:
        sections += [
            "",
            "REVISION REQUIRED — The previous plan was reviewed and found not ready.",
            "Fix the issues below and rewrite the sprint plan.",
            "",
            _fence("FEEDBACK", feedback.strip()),
        ]

    sections += [
        "",
        "CONSTRAINT: Each sprint must leave the project in a working state",
        "(tests pass, no broken imports).",
        "",
        _PLANNER_OUTPUT_CONTRACT,
    ]
    return "\n".join(sections)


def _sprint_yaml(sprint: Sprint) -> str:
    data = {
        "id": sprint.id,
        "primary_goal": sprint.primary_goal,
        "status": sprint.status,
    }
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _task_index(task: Task) -> str:
    deps = f" depends_on={task.depends_on}" if task.depends_on else ""
    return (
        f"- {task.id} [{task.status}]{deps}: "
        f"{task.intent.strip().splitlines()[0][:_INTENT_SNIPPET_CHARS]}"
    )


def _task_yaml(task: Task) -> str:
    """Task frontmatter YAML — mirrors the on-disk shape from `Task._save`."""
    data = {
        "id": task.id,
        "depends_on": list(task.depends_on),
        "status": task.status,
        "eval": [e.to_dict() for e in task.eval],
        "attempts": [
            {
                "started_at": a.started_at.isoformat() if a.started_at else None,
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                "failed_at": a.failed_at.isoformat() if a.failed_at else None,
                "error": a.error,
            }
            for a in task.attempts
        ],
        "summary": task.summary,
    }
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _sprint_full_render(sprint: Sprint) -> str:
    """Render the sprint+tasks manifest the way a worker sees it.

    Sprint frontmatter, sprint context, then each task's frontmatter
    plus intent body. Used by the critic and judge so they review the
    same artefact the worker will execute against.
    """
    parts: list[str] = [
        _sprint_yaml(sprint),
        "",
        sprint.context.strip(),
        "",
        "## Tasks",
    ]
    if not sprint.tasks:
        parts += ["", "(no tasks)"]
    else:
        for task in sprint.tasks:
            parts += [
                "",
                f"### Task {task.id}",
                _task_yaml(task),
                "",
                task.intent.strip(),
            ]
    return "\n".join(parts)


def build_critic_prompt(sprint: Sprint, goal: Goal) -> str:
    """Critic prompt: review a sprint draft against the target goal."""
    sections = [
        "Review this sprint draft against its target goal. Your job is to identify",
        "what the plan missed — gaps, ambiguities, missing DoD, ordering issues,",
        "unstated assumptions — and return actionable critique.",
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT MANIFEST", _sprint_full_render(sprint)),
        "",
        "Be specific. Vague concerns ('needs more detail') do not improve the plan.",
    ]
    return "\n".join(sections)


def build_judge_prompt(sprint: Sprint, goal: Goal, critic_notes: str) -> str:
    """Judge prompt: approve or reject a sprint given critic notes."""
    sections = [
        "Judge whether this sprint is ready for autonomous execution against its goal.",
        "Read the sprint draft, the target goal, and the critic's notes, then decide.",
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT MANIFEST", _sprint_full_render(sprint)),
        "",
        _fence("CRITIC NOTES", critic_notes.strip() or "(no critic notes)"),
        "",
        "Respond with EXACTLY one of:",
        "",
        "VERDICT: READY",
        "(or)",
        "VERDICT: NOT_READY",
        "",
        "Followed by feedback explaining the decision. If NOT_READY, list the",
        "specific changes required before the sprint can be approved.",
    ]
    return "\n".join(sections)


_ROADMAP_OUTPUT_CONTRACT = """\
OUTPUT CONTRACT — strict. The orchestrator parses your response text by
splitting on `### FILE:` headers. Do not write to disk; return one response
containing one roadmap block and one block per goal.

Format (exact):

    ### FILE: roadmap.md
    ---
    archetype: <archetype-id>
    eval: []
    ---

    # Roadmap
    <narrative>

    ### FILE: goal-<id>.md
    ---
    id: <goal-id>
    priority: 1
    status: pending
    eval: []
    achieved_by: []
    summary: null
    ---

    # Goal: <title>
    <intent>

Rules:
- Exactly one `roadmap.md` block.
- One `goal-<id>.md` block per goal; ids slug-style.
- Priority ordering starts at 1 and increments.
- No prose outside the blocks."""


def build_analyst_prompt(topic: str, project_root: Path) -> str:
    """Analyst prompt: topic + project root. Output is raw markdown (no FILE: envelope)."""
    return (
        f"Analyse the topic `{topic}` for the project at `{project_root}`. "
        "Explore the codebase as needed, then return a concise markdown summary "
        "of your findings. Your entire response becomes the research document — "
        "no leading preamble, no file envelope.\n"
    )


def build_roadmap_prompt(
    project_root: Path,
    *,
    research: str | None = None,
    existing_roadmap: str | None = None,
) -> str:
    """Roadmap prompt: create or revise. Emits `### FILE:` envelopes parsed by the CLI."""
    sections: list[str] = []
    if existing_roadmap is not None:
        sections.append(
            "Revise the existing roadmap for this project. Update goals, add or "
            "remove them as needed, and rewrite the narrative."
        )
        sections += ["", _fence("EXISTING ROADMAP", existing_roadmap.strip())]
    else:
        sections.append(
            "Create a shipping roadmap for this project. Pick a concrete target, "
            "write the narrative, and enumerate initial goals."
        )
    sections += ["", f"Project root: {project_root}"]
    if research:
        sections += ["", _fence("RESEARCH", research.strip())]
    sections += ["", _ROADMAP_OUTPUT_CONTRACT]
    return "\n".join(sections)


def build_evaluator_prompt(sprint: Sprint, goal: Goal, roadmap: Roadmap) -> str:
    """Evaluator prompt: decide whether the goal is achieved after a sprint."""
    task_lines = [_task_index(t) for t in sprint.tasks]
    sections = [
        "Assess whether the target goal has been achieved given the sprint just",
        "completed and the overall roadmap context.",
        "",
        f"Archetype: {roadmap.archetype}",
        "",
        _fence("ROADMAP NARRATIVE", roadmap.narrative.strip()),
        "",
        _fence("TARGET GOAL", f"{_goal_yaml(goal)}\n\n{goal.intent.strip()}"),
        "",
        _fence("SPRINT OUTCOME", f"{_sprint_yaml(sprint)}\n\n{sprint.context.strip()}"),
        "",
        _fence("TASK LIST", "\n".join(task_lines) if task_lines else "(no tasks)"),
    ]
    if sprint.summary:
        sections += ["", _fence("SPRINT SUMMARY", sprint.summary.strip())]

    sections += [
        "",
        "Respond with EXACTLY one of:",
        "",
        "GOAL_MET: YES",
        "(or)",
        "GOAL_MET: NO",
        "",
        "Followed by a concise assessment (2-5 sentences). If not satisfied,",
        "describe what remains.",
    ]
    return "\n".join(sections)


# ---------- Lisa (research loop) ----------


_DECOMPOSER_ROLE_GUARD = """\
## Your role in the map-reduce

You are the MAP step. The downstream synthesiser is the REDUCE step. Your
output must contain only knowledge-gathering enquiries — questions whose
answer requires going out and finding new information from primary
sources. Anything that combines, contrasts, ranks, summarises, or
synthesises *across* findings is the synthesiser's job, not yours.

Each enquiry MUST be:
- A line of enquiry — a single question whose answer is fact, code, or
  evidence retrievable from one or a handful of primary sources.
- Independent — answerable without reading another enquiry's findings.
- Narrow enough to dispatch to one researcher in one pass.

Each enquiry MUST NOT be:
- A synthesis or comparison task ("synthesise across all frameworks",
  "compare X and Y", "rank by impact", "identify the most worth borrowing").
- A summarisation task ("summarise the key findings", "produce an executive
  summary").
- A meta-evaluation ("which framework is best", "what should we adopt").
- Phrased as "synthesise / compare / rank / summarise / evaluate" — those
  verbs belong downstream.

If the brief asks for a comparison or ranking, your job is to produce the
fact-finding enquiries that make the comparison possible. The synthesiser
will then do the comparing. Do not pre-empt it."""


_DECOMPOSER_OUTPUT_CONTRACT = """\
## Output Contract

Emit one or more enquiry envelopes. Format:

### ENQUIRY: <one-line knowledge-gathering question>
<optional 1-3 lines of scope / context for the researcher>

### ENQUIRY: <next question>
...

Rules:
- No prose outside any envelope.
- One question per envelope; split with "and" / "as well as".
- Knowledge-gathering only — see "Your role in the map-reduce" above.
- Aim for 3-6 envelopes; the loop caps at the configured maximum."""


def build_decomposer_prompt(run: ResearchRun, prior_gaps: list[str], steer: str | None) -> str:
    """Decomposer prompt: brief + optional prior gaps + optional steer."""
    sections = [
        "Decompose the following research brief into focused enquiries.",
        "",
        _fence("BRIEF", run.brief.strip()),
    ]
    if prior_gaps:
        gap_text = "\n".join(f"- {g}" for g in prior_gaps)
        sections += [
            "",
            f"This is iteration {run.iteration + 1}. Coverage was judged INSUFFICIENT after the",
            "previous iteration. Direct the new enquiries at the gaps below — do not",
            "re-pose anything already adequately covered.",
            "",
            _fence("PRIOR GAPS", gap_text),
        ]
    if steer:
        sections += [
            "",
            "A human dropped the following steer into the run directory between",
            "iterations. Treat it as advisory context for decomposition only — it",
            "does not modify the brief.",
            "",
            _fence("STEER", steer.strip()),
        ]
    sections += ["", _DECOMPOSER_ROLE_GUARD, "", _DECOMPOSER_OUTPUT_CONTRACT]
    return "\n".join(sections)


def build_researcher_prompt(brief: str, enquiry: Enquiry) -> str:
    """Researcher prompt: brief (context) + one enquiry (the actual job)."""
    sections = [
        "Investigate the following enquiry. Return raw markdown findings.",
        "",
        _fence("RESEARCH BRIEF (CONTEXT)", brief.strip()),
        "",
        _fence(f"YOUR ENQUIRY ({enquiry.id})", enquiry.question.strip()),
        "",
        "Output rules:",
        "- Raw markdown only — no `### ENQUIRY:` header, no file envelope.",
        "- End with an optional `## Sources` section (bullet list, one per",
        "  source). Omit `## Sources` if you have nothing to cite.",
        "- Answer this enquiry only — not the whole brief, not adjacent",
        "  enquiries.",
    ]
    return "\n".join(sections)


def _enquiry_findings_block(enq: Enquiry) -> str:
    body = enq.findings.strip() if enq.findings else "(no findings)"
    sources = "\n".join(f"- {s}" for s in enq.sources) if enq.sources else "(no sources)"
    return (
        f"### enquiry-{enq.id} (iteration {enq.iteration})\n"
        f"Q: {enq.question.strip()}\n\n"
        f"{body}\n\n"
        f"Sources:\n{sources}"
    )


def build_synthesiser_prompt(run: ResearchRun) -> str:
    """Synthesiser prompt (report mode): brief + all completed enquiries → report."""
    completed = [e for e in run.enquiries if e.status == "completed"]
    failed = [e for e in run.enquiries if e.status == "failed"]
    blocks = [_enquiry_findings_block(e) for e in completed]
    sections = [
        "Synthesise the findings of the parallel researchers into a single",
        "coherent report covering the brief.",
        "",
        _fence("BRIEF", run.brief.strip()),
        "",
        _fence(
            "ENQUIRY FINDINGS",
            "\n\n".join(blocks) if blocks else "(no completed enquiries)",
        ),
    ]
    if failed:
        failed_lines = [
            f"- enquiry-{e.id} (iteration {e.iteration}): {e.error or 'failed'}" for e in failed
        ]
        sections += ["", _fence("FAILED ENQUIRIES", "\n".join(failed_lines))]
    sections += [
        "",
        "Output: raw markdown report. Suggested top-level sections:",
        "`# <slug>`, `## Summary`, `## Findings`, `## Open Questions`. The Open",
        "Questions section is your honest accounting of where evidence is thin",
        "— it feeds the next iteration's decomposer if coverage is insufficient.",
    ]
    return "\n".join(sections)


def build_summariser_prompt(run: ResearchRun, report_text: str) -> str:
    """Summariser prompt (synthesiser role, summary mode): report → 3-5 sentence handoff."""
    sections = [
        "Distil the following research report into a 3-5 sentence handoff",
        "summary suitable for a downstream consumer (roadmap writer, planner,",
        "or human reviewer).",
        "",
        _fence("BRIEF", run.brief.strip()),
        "",
        _fence("REPORT", report_text.strip()),
        "",
        "Output: 3-5 sentences of raw markdown. No headings, no bullet lists,",
        "no preamble. The reader needs the gist in seconds.",
    ]
    return "\n".join(sections)


def _extract_open_questions(report_text: str) -> str | None:
    """Pull the synthesiser's `## Open Questions` section out of a report.

    Returns the body of the section (no heading), or None if the section is
    absent / empty. Used by the judge prompt as a forcing function so the
    judge cannot ignore the synthesiser's own admission of gaps.
    """
    lines = report_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "## open questions":
            start = i + 1
            break
    if start is None:
        return None
    body: list[str] = []
    for ln in lines[start:]:
        if ln.strip().startswith("##"):
            break
        body.append(ln)
    text = "\n".join(body).strip()
    return text or None


def build_research_judge_prompt(run: ResearchRun, report_text: str) -> str:
    """Research-judge prompt: brief + report + extracted Open Questions → coverage verdict.

    Forces the judge to (a) triage every open question the synthesiser raised,
    classifying each as GAP_WORTH_CLOSING / OUT_OF_SCOPE / ANSWERED_ELSEWHERE
    with a reason, before (b) issuing the COVERAGE verdict. SATISFIED is
    legitimate only when zero items remain in GAP_WORTH_CLOSING. This addresses
    the calibration concern in phase-5-lisa.md §14 (judge proved too lenient
    on the first real-use dossier — it explained away the synthesiser's open
    questions instead of engaging with them).
    """
    sections = [
        "Decide whether the following research report adequately covers the",
        "brief that prompted it. The brief is canonical — if it lists",
        "mandatory dimensions, mandatory frameworks, mandatory comparisons,",
        "or any other must-cover items, those are non-negotiable. A missing",
        "must-cover item is INSUFFICIENT, not OUT_OF_SCOPE.",
        "",
        _fence("BRIEF", run.brief.strip()),
        "",
        _fence("REPORT", report_text.strip()),
    ]

    open_qs = _extract_open_questions(report_text)
    if open_qs:
        sections += [
            "",
            "The synthesiser's own `## Open Questions` section, extracted",
            "verbatim. You MUST engage with every item below — silently",
            "ignoring or hand-waving an open question is the failure mode",
            "this prompt is calibrated against.",
            "",
            _fence("SYNTHESISER OPEN QUESTIONS", open_qs),
        ]

    sections += [
        "",
        "## Step 1 — Triage of synthesiser open questions",
        "",
        "If the SYNTHESISER OPEN QUESTIONS block above is present, list each",
        "item and classify it as exactly one of:",
        "",
        "- **GAP_WORTH_CLOSING** — closing this would materially improve the",
        "  answer to the brief. State *what concrete value* a follow-up",
        "  iteration would add (a fact established, a comparison enabled, a",
        "  risk surfaced, etc.). Vague value-claims do not count.",
        "- **OUT_OF_SCOPE** — explicitly disallowed by the brief, or beyond",
        "  what the loop can do (e.g. requires interviewing humans, requires",
        "  a benchmark that does not exist). Cite the brief clause or",
        "  capability constraint that justifies this.",
        "- **ANSWERED_ELSEWHERE** — already addressed by another section of",
        "  the report. Cite the report section.",
        "",
        "Format:",
        "",
        "## Triage",
        "- <verbatim open question>: GAP_WORTH_CLOSING — <concrete value-add>",
        "- <verbatim open question>: OUT_OF_SCOPE — <brief clause or constraint>",
        "- <verbatim open question>: ANSWERED_ELSEWHERE — <report section>",
        "",
        "If no SYNTHESISER OPEN QUESTIONS block is present, write `## Triage`",
        "followed by `- (synthesiser raised no explicit open questions)`.",
        "",
        "## Step 2 — Brief mandatory items",
        "",
        "Inspect the BRIEF for any explicitly named must-cover items",
        "(numbered dimensions, listed frameworks, named deliverables, etc.).",
        "For each, decide COVERED or GAP_WORTH_CLOSING.",
        "",
        "## Brief Coverage",
        "- <mandatory item from brief>: COVERED — <where in the report>",
        "- <mandatory item from brief>: GAP_WORTH_CLOSING — <what is missing>",
        "",
        "If the brief has no enumerable must-cover items, write",
        "`- (no enumerable must-cover items)`.",
        "",
        "## Step 3 — Verdict",
        "",
        "SATISFIED requires ZERO entries in GAP_WORTH_CLOSING across both",
        "Step 1 and Step 2. One or more GAP_WORTH_CLOSING entries means",
        "INSUFFICIENT — full stop, regardless of how 'minor' they feel.",
        "",
        "Respond with EXACTLY one of:",
        "",
        "COVERAGE: SATISFIED",
        "(or)",
        "COVERAGE: INSUFFICIENT",
        "",
        "Then a `## Gaps` section listing every GAP_WORTH_CLOSING item",
        "(from either step) with its value-add justification. When SATISFIED,",
        "the Gaps section may still list any OUT_OF_SCOPE items for the",
        "permanent record; the loop will not iterate on them.",
        "",
        "Format:",
        "",
        "## Gaps",
        "- <gap>: <why closing this would add concrete value>",
    ]
    return "\n".join(sections)


# ---------- Frink (experiment loop) ----------


def _kb_listing(exp: Experiment) -> str:
    """File paths under the experiment's kb/, for on-demand Read by the runner."""
    if exp._dir is None:
        return "(no kb)"
    kb = exp._dir / "kb"
    if not kb.is_dir():
        return "(no kb)"
    lines: list[str] = []
    for p in sorted(kb.rglob("*")):
        if p.is_file() or p.is_symlink():
            lines.append(str(p))
    return "\n".join(lines) if lines else "(kb is empty)"


def _prior_lap_summary(lap: Lap) -> str:
    reason = (lap.verdict_reason or "").strip().replace("\n", " ")
    return f"- {lap.id} [{lap.verdict}] spec: {lap.spec.strip()[:200]} | reason: {reason[:300]}"


_FRINK_CLI_ATOMS = """\
autopilot roadmap create/revise      — roadmap + goal files
autopilot sprint prepare             — plan + critique + judge to approval
autopilot sprint execute             — run the approved sprint
autopilot sprint plan/critique/judge/evaluate — individual planning atoms
autopilot task run <file>            — one task with retries
autopilot eval show/run <ref>        — inspect / execute evals
autopilot analyse [--topic]          — codebase analysis
autopilot lisa --brief[-text]        — research loop
autopilot ralph                      — full build loop"""


def build_frink_runner_prompt(exp: Experiment, lap_id: str) -> str:
    """Runner prompt: experiment + prior laps + kb listing + CLI atoms. Entities in."""
    sections = [
        f"Plan and execute one experiment lap ({lap_id}, mode: {exp.mode}).",
        "",
        _fence("OBJECTIVE", exp.objective.strip()),
        "",
        _fence("RUBRIC (frozen — you cannot change it)", exp.rubric.strip()),
    ]
    if exp.goal_id:
        sections += ["", f"Linked goal: {exp.goal_id}"]
    prior = exp.laps[-3:]
    if prior:
        sections += ["", _fence("PRIOR LAPS", "\n".join(_prior_lap_summary(x) for x in prior))]
    sections += [
        "",
        _fence("KNOWLEDGE BASE (read on demand with the Read tool)", _kb_listing(exp)),
        "",
        _fence("AVAILABLE AUTOPILOT CLI COMMANDS", _FRINK_CLI_ATOMS),
        "",
        "You are on a dedicated git branch for this lap. Decide ONE thing to",
        "try this lap, do it, and commit your changes. Collect the signals the",
        "stop-judge will need to verdict the lap against the rubric.",
        "",
        "You may write scratch notes to kb/ad-hoc/ only; the rest of kb/ is",
        "read-only for you.",
        "",
        "End your response with EXACTLY this structure:",
        "",
        "### SPEC",
        "<one paragraph: what this lap tried, and why>",
        "",
        "### SIGNALS",
        "```yaml",
        "<mapping: the signals this lap produced, for the stop-judge>",
        "```",
    ]
    return "\n".join(sections)


def build_frink_stop_judge_prompt(exp: Experiment, spec: str, signals: dict[str, Any]) -> str:
    """Stop-judge prompt: frozen rubric + lap spec/signals + prior verdicts."""
    signals_text = yaml.safe_dump(signals, sort_keys=False) if signals else "(none)"
    sections = [
        "Verdict this experiment lap against the frozen rubric.",
        "",
        _fence("OBJECTIVE", exp.objective.strip()),
        "",
        _fence("RUBRIC (frozen)", exp.rubric.strip()),
        "",
        _fence("THIS LAP'S SPEC", spec.strip()),
        "",
        _fence("THIS LAP'S SIGNALS", signals_text.strip()),
    ]
    if exp.laps:
        sections += [
            "",
            _fence("PRIOR LAPS", "\n".join(_prior_lap_summary(x) for x in exp.laps)),
        ]
    sections += [
        "",
        "Respond with EXACTLY:",
        "",
        "VERDICT: merge|discard|iterate",
        "REASON: <one paragraph justifying against the rubric>",
        "DONE: yes|no",
        "",
        "DONE: yes on a merge verdict means the experiment's objective is met",
        "and the loop should exit. Omit nothing.",
    ]
    return "\n".join(sections)


def build_frink_reviewer_prompt(exp: Experiment) -> str:
    """Reviewer prompt: full experiment + laps + kb. Runs once, on terminal state."""
    laps_text = "\n".join(_prior_lap_summary(x) for x in exp.laps) or "(no laps)"
    sections = [
        f"Review completed experiment {exp.id} (mode: {exp.mode}, status: {exp.status}).",
        "",
        _fence("OBJECTIVE", exp.objective.strip()),
        "",
        _fence("RUBRIC", exp.rubric.strip()),
        "",
        _fence("LAPS", laps_text),
        "",
        _fence("KNOWLEDGE BASE", _kb_listing(exp)),
        "",
        "Propose actionable improvements to the autopilot implementation,",
        "agent prompts, skills, runbooks, or knowledge base — based ONLY on",
        "what this experiment actually observed. Do not generalise beyond the",
        "observations. Do not propose speculative changes. Rank proposals by",
        "signal strength. A valid output is 'no actionable learnings.'",
        "",
        "Output format:",
        "",
        f"# Review — {exp.id}",
        "",
        "## Summary",
        "<what happened, 2-3 sentences>",
        "",
        "## Proposals",
        "",
        "### P1 — <target>",
        "**Change:** <what to edit>",
        "**Evidence:** <which lap(s), which signals supported this>",
        "**Signal strength:** low | medium | high",
        "",
        "## No-go (observations that did not yield a proposal)",
        "<honest list of things that looked like patterns but had only one data point>",
    ]
    return "\n".join(sections)
