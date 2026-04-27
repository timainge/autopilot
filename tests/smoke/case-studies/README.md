# Case-Study Smokes

Real-agent, real-money smokes that run autopilot end-to-end against
pre-seeded subject applications. **Not part of the default suite.**

## Why separate from `tests/smoke/{a,s,f}*.sh`

The default suite is fake-agent driven — fast, deterministic, free. These
smokes run real agent calls: each invocation costs real money ($1–5 per
run) and takes minutes. They answer different questions:

| Default suite | Case-study smokes |
|---|---|
| Does the mechanism wire up? | Does the pipeline hold together under real agent weight? |
| Fake agents, scripted outputs | Live SDK, live model calls |
| Milliseconds | Minutes |
| Free | $1–5 per run |
| Wired into `run.sh` default / fault | Manually invoked per sprint / per milestone |

Run case-study smokes **after landing a sprint increment** to catch
regressions where new machinery (eval, inspector, judge, etc.) blows
through budget or hangs on real model behaviour that fake agents don't
reproduce.

## Running

Real-agent smokes are gated behind an environment variable to prevent
accidental expense:

```bash
AUTOPILOT_REAL_AGENT_OK=1 tests/smoke/case-studies/cadence/cadence-plumbing.sh
```

Without the gate set, the script exits immediately with a clear message.

### Optional env vars

- **`VERBOSE=1`** — stream the JSONL events from `autopilot ralph` to
  stderr in real time (also tee'd to `<tmpdir>/.dev/logs/ralph-stderr.log`).
  Without it the run is quiet until the summary at the end. Useful when
  you want to watch the loop progress or attach to a long run.

- **`AUTOPILOT_MODEL=<haiku|sonnet|opus>`** — collapse every role's model
  to one tier. Useful for stress-testing prompts on a smaller / faster /
  cheaper model than the per-role defaults (default: planner +
  roadmap_writer on opus, others on sonnet). Example:

  ```bash
  AUTOPILOT_REAL_AGENT_OK=1 AUTOPILOT_MODEL=haiku VERBOSE=1 \
    tests/smoke/case-studies/cadence/cadence-plumbing.sh
  ```

  An invalid value raises `ConfigError` at startup.

## Structure

```
case-studies/
  README.md                    ← this file
  <subject>/
    seed/                      ← pre-seeded starter; copied to a tmpdir each run
    baseline.json              ← canonical cost/time from a known-good run
    <subject>-plumbing.sh      ← the smoke script
    (future) <subject>-cold.sh ← cold-start variant (roadmap-only, no seed)
```

Each subject owns its own dir; tests never mutate the seed. Each run
copies the seed into a fresh tmpdir, so the seed on disk is immutable.

## Subjects

- **cadence** — FastAPI time-tracking API. First case study. Covers
  the 80% case (feature-add goals on an existing codebase, not
  scaffold/troubleshoot admin work). Future siblings will add
  `cadence-cli`, `cadence-web`, `cadence-mcp` as multi-archetype eval
  work lands in Phase 4.

## Baseline discipline

The first successful run captures a `baseline.json` with wall-clock + cost
+ sprint count for that autopilot ref. Subsequent runs compare — a
2×-over-baseline result is a test failure. The baseline can be
regenerated (delete the file, re-run) when an intentional change alters
the expected envelope. Regeneration should be a deliberate commit with
rationale, not a silent overwrite.
