# autopilot

[![PyPI](https://img.shields.io/pypi/v/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![CI](https://github.com/timainge/autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/timainge/autopilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/claude-autopilot)](https://pypi.org/project/claude-autopilot/)
[![Docs](https://img.shields.io/badge/docs-github--pages-blue)](https://timainge.github.io/autopilot)

Autonomous loops for Claude Code, persisted as legible filesystem state.

Autopilot runs bounded, budget-capped loops — research, build, and (soon)
experiment — where Claude Code agents do all the thinking and a thin
Python harness owns lifecycle, retries, budgets, and persistence. Every
plan, task, verdict, and finding lives as a markdown file under `.dev/`,
so you can read, diff, and steer a run with nothing but a text editor.

---

## The loops

Codenames name self-driving loops — things that plan, act, evaluate, and
repeat under a budget. Everything else is a plain `noun verb` command.

| Loop | Command | Shape |
|------|---------|-------|
| **ralph** — build | `autopilot ralph` | plan sprint → execute tasks → evaluate goal → repeat until goals met |
| **lisa** — research | `autopilot lisa` | decompose brief → parallel enquiries → synthesise → judge coverage → repeat until satisfied |
| **frink** — experiment | `autopilot frink start` | plan lap → run in branch → judge against frozen rubric → merge/discard/iterate → repeat |

Ralph's heavier scaffolding — a fresh Claude Code session per task,
retries, adversarial critic/judge gates on every plan — is deliberate.
Frontier models often don't need that much structure; smaller, local, or
open-source models do. The harness is model-agnostic where the model is
weakest.

---

## Install

```bash
pip install claude-autopilot
# or
uv pip install claude-autopilot
```

Requires a Claude API key from [console.anthropic.com](https://console.anthropic.com):

```bash
ANTHROPIC_API_KEY=your-key-here autopilot ralph .
```

> **Note:** Don't export `ANTHROPIC_API_KEY` globally in your shell — Claude Code picks it up
> and will bill interactive sessions at API rates instead of your subscription. Pass it inline
> or via a `.env` file.

---

## Quick start

**Build loop** — define goals, then let ralph drive:

```bash
autopilot roadmap create .    # agent writes .dev/roadmap.md + goal files
autopilot ralph .             # prepare sprint → execute → evaluate, repeat
```

**Step by step** — same machinery, one stage at a time:

```bash
autopilot sprint prepare .    # plan + critique + judge until approved
autopilot sprint execute .    # run each task in a fresh session
autopilot sprint evaluate .   # judge the goal against its evals
```

**Research loop** — deep research with a coverage judge:

```bash
autopilot lisa . --brief-text "How should we approach X?"
autopilot lisa . --brief brief.md --max-iterations 5
```

Lisa decomposes the brief into enquiries, researches them in parallel,
synthesises a report, and iterates on coverage gaps until the judge is
satisfied or budget/iteration caps bind. Output lands in
`.dev/research/<slug>/` — `report.md`, `summary.md`, and one file per
enquiry. Drop a `steer.md` into the run directory mid-flight to redirect
the next iteration without stopping the loop.

Feed research into a build:

```bash
autopilot roadmap create . --research .dev/research/<slug>/summary.md
```

---

## Commands

### Loops

- `autopilot ralph [<project>]` — build loop. Requires `.dev/roadmap.md`.
  Stops on goals met, an escalated plan, a stuck sprint, or `max_sprints`.
- `autopilot lisa [<project>] (--brief <file> | --brief-text <str>) [--slug <s>] [--max-iterations <n>]`
  — research loop.
- `autopilot frink start [<project>] --mode build|tune|research --objective <str|@file> --rubric <str|@file> [--goal <id>] [--hil]`
  — experiment loop. See [Running an experiment](#running-an-experiment-frink)
  for the full walkthrough; `frink status` and `frink review` inspect a
  run and re-run the reviewer.

### Composed commands

- `autopilot sprint prepare [--goal <goal-id>]` — planner drafts a
  sprint; critic reviews adversarially; judge approves or sends it back
  (up to `max_judge_rounds`). Only approved sprints can execute.
- `autopilot sprint execute [--sprint <id>]` — runs each task of the
  approved sprint in a fresh Claude Code session, retrying failures up
  to `max_task_attempts`, running each task's evals after each attempt.

### Atomic commands

One agent call (or one state transition) each:

```bash
autopilot roadmap create [--research <path>]   # write roadmap + goals
autopilot roadmap revise                       # revise existing roadmap
autopilot sprint plan [--goal <goal-id>]       # planner only, no gates
autopilot sprint critique [--sprint <id>]      # critic pass on a draft
autopilot sprint judge [--sprint <id>]         # judge verdict on a draft
autopilot sprint evaluate [--sprint <id>]      # goal evals + evaluator
autopilot task run <task-file>                 # one task, with retries
autopilot task retry <task-file>               # retry a failed task
autopilot eval show <ref>                      # print eval payload
autopilot eval run <ref>                       # execute eval(s), record runs
autopilot analyse [--topic <t>]                # codebase analysis → .dev/analysis/
```

Eval refs address evals by entity: `task:<sprint-id>/<task-id>[#i]`,
`sprint:<sprint-id>[#i]`, `goal:<goal-id>[#i]`.

---

## Running an experiment (frink)

An experiment is a bounded loop of **laps**. Each lap, a runner agent
decides one thing to try and does it on a dedicated git branch; a
stop-judge on a **different model** (enforced) verdicts the lap against
a rubric that was **frozen when the experiment started** — so an
unattended loop can't game its own yardstick. When the experiment ends
(done, budget, or iteration cap), a reviewer writes `review.md`:
evidence-bound proposals for what to change, ranked by signal strength.

### 1. Prerequisites

- The project is a git repository with a **clean working tree** — frink
  cuts, merges, and deletes `exp/<id>/lap/<id>` branches, and any
  uncommitted changes you leave lying around get swept into the first
  lap's commit as if they were lap work.
- `.dev/` is gitignored (frink refuses to start otherwise — orchestration
  state must not ride along on lap branches).

### 2. Write the objective and the rubric

The **objective** says what you're exploring. The **rubric** says how a
lap is judged — make it measurable and checkable, ideally with commands
the judge can run or artifacts it can read. It cannot change mid-run; if
it's wrong, finish or stop the experiment and start a new one.

```markdown
<!-- objective.md -->
Raise the planner's task-spec quality: task bodies should carry concrete
done-criteria a worker can verify, without regressing suite pass rate.
```

```markdown
<!-- rubric.md -->
A lap is MERGE-worthy when all hold:
- `tests/smoke/run.sh` exits 0 (floor — never trade this away).
- Task bodies in the produced sprint each contain an explicit
  "**Done**:" criterion referencing a runnable check.
- Wall-clock regression vs the baseline (1106s) is under 2x.
The experiment is DONE when a merged lap's improvement holds for two
consecutive laps.
```

### 3. Start it

```bash
autopilot frink start . --mode tune \
  --objective @objective.md --rubric @rubric.md
```

`--mode` frames the runner's behaviour — it's an instruction, not a
different engine:

| Mode | The runner spends its lap... |
|------|------------------------------|
| `build` | driving autopilot CLI commands against an objective (link a goal with `--goal <id>`) |
| `tune` | varying one config/prompt/model and measuring the effect |
| `research` | testing a hypothesis and reporting what it found |

Each lap you'll see: branch `exp/exp-001/lap/lap-NNN` created → runner
works and commits → stop-judge reads the runner's SPEC/SIGNALS and
verdicts **merge** (change is kept — merged to your branch), **discard**
(branch deleted), or **iterate** (branch kept; next lap continues from
it). A `merge` verdict with `DONE: yes` completes the experiment.

### 4. Watch and steer

```bash
autopilot frink status .          # frontmatter + last laps + cost
cat .dev/experiments/exp-001/lap-002.md   # any lap: spec, signals, verdict
```

With `--hil`, no verdict is applied until you approve it. Each lap
writes `lap-NNN.pending.md` containing the proposed verdict, then blocks:

- **Accept as proposed** — delete the file.
- **Override** — edit it to:
  ```yaml
  accepted: true
  override_verdict: discard        # merge | discard | iterate
  override_reason: "regression not worth it"
  ```
- **Reject** — `accepted: false` (lap is discarded).
- Do nothing for `frink_hil_timeout_sec` (default 1h) → discard.

### 5. Read the results

The run lives in `.dev/experiments/exp-001/`: `exp-001.md` (status,
cost, rubric), one `lap-NNN.md` per lap, and `review.md` — the
reviewer's proposals. Terminal states: `completed` (judge said done),
`exhausted` (iteration or budget cap), `stopped` (a role failed or you
aborted). The reviewer runs on every terminal state, including aborts.

Useful afterwards:

```bash
autopilot frink review .          # re-run the reviewer (e.g. after edits)
autopilot frink start . ...       # same objective + status=running → resumes
```

Caps and models come from config: `frink_max_iterations` (20),
`frink_max_cost_per_run_usd` (25.0), and `frink_runner_model` /
`frink_stop_judge_model` (must differ) / `frink_reviewer_model`.

---

## The `.dev/` directory

`.dev/` is live orchestration state — what is planned, in progress,
succeeded, or failed at any moment. Add it to `.gitignore`.

```
.dev/
  roadmap.md                  # goals, archetype, narrative
  goals/goal-<id>.md          # one file per goal: status, evals, history
  sprints/sprint-NNN/
    sprint-NNN.md             # sprint frontmatter + revision rounds
    task-NNN.md               # one file per task: spec, attempts, evals
  research/<slug>/            # lisa runs: run.md, enquiry-*.md, report.md,
                              #   gaps.md, summary.md, steer.md (yours)
  experiments/exp-NNN/        # frink runs: exp-NNN.md, lap-NNN.md,
                              #   kb/, review.md
  analysis/<topic>.md         # analyse output
  logs/run-*.jsonl            # structured agent-call traces
```

Domain hierarchy: **Roadmap → Goals → Sprints → Tasks**. Entities own
their persistence — every mutation writes its file atomically, so a
`kill -9` mid-run leaves legible state and re-running resumes cleanly.

---

## Configuration

Layered: defaults < `~/.config/autopilot/config.toml` <
`<project>/.dev/autopilot.toml`. Flat TOML keys, validated strictly —
unknown keys are an error.

```toml
# .dev/autopilot.toml
max_task_attempts = 2
max_judge_rounds = 2
max_sprints = 10
max_cost_per_call_usd = 2.0
max_cost_per_run_usd = 50.0

# per-role models
worker_model = "claude-sonnet-4-6"
planner_model = "claude-opus-4-7"

# lisa
max_research_iterations = 3
max_enquiries_per_iteration = 6
max_parallel_research = 3
max_cost_per_research_run_usd = 5.0

# frink
frink_max_iterations = 20
frink_max_cost_per_run_usd = 25.0
frink_runner_model = "claude-sonnet-4-6"
frink_stop_judge_model = "claude-opus-4-7"   # must differ from runner_model
```

`AUTOPILOT_MODEL=haiku|sonnet|opus` collapses every role to one model —
useful for stress-testing prompts on a cheaper model, or pointing the
whole harness at a single capability tier.

---

## Agent roles

Each role is a markdown file (`src/autopilot/agents/roles/*.md`): YAML
frontmatter (tools, permission mode, budget) + system prompt.

| Role | Used by | Owns |
|------|---------|------|
| `planner` | `sprint plan/prepare`, `ralph` | drafting the sprint + tasks |
| `critic` | `sprint critique/prepare`, `ralph` | adversarial plan review |
| `judge` | `sprint judge/prepare`, `ralph` | READY / NOT_READY verdict |
| `worker` | `sprint execute`, `task run`, `ralph` | implementing one task |
| `evaluator` | `sprint evaluate`, `ralph` | goal-achievement verdict |
| `roadmap` | `roadmap create/revise` | roadmap + goal files |
| `analyst` | `analyse` | codebase analysis |
| `decomposer` | `lisa` | brief → enquiry list |
| `researcher` | `lisa` | one enquiry → findings + sources |
| `synthesiser` | `lisa` | enquiries → report / summary |
| `research-judge` | `lisa` | SATISFIED / INSUFFICIENT + gaps |
| `frink-runner` | `frink` | plans + executes one lap on its branch |
| `frink-stop-judge` | `frink` | merge / discard / iterate verdict |
| `frink-reviewer` | `frink` | evidence-bound review on terminal state |

---

## Design notes

**Why the Agent SDK, not CLI pipes?** The SDK wraps Claude Code
programmatically — same tools, streaming, error handling. Each call is a
fresh session with clean context.

**Why markdown state instead of a database?** The state doubles as
documentation. A human can read a sprint, edit a goal, or steer a
research run with any editor — and agents parse it strictly (unknown
frontmatter keys are errors, not warnings).

**Why an adversarial gate on plans?** A bad plan executed autonomously
is expensive. The critic and judge are separate roles with separate
prompts; the judge can send a plan back with feedback before anything
runs.

**Why sequential tasks?** Simpler to debug, cheaper, no merge
conflicts. Parallelism lives at the experiment-loop level (branch per
lap) rather than the task level.

**Why freeze the rubric?** Borrowed from karpathy/autoresearch: the eval
primitive is immutable for the life of the experiment, so an unattended
loop can't game its own yardstick. Re-scoping means a new experiment.
