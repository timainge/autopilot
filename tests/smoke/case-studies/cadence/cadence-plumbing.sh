#!/usr/bin/env bash
# Cadence plumbing smoke — FastAPI case study.
#
# Exercises `autopilot ralph` against a pre-seeded FastAPI app with three
# feature-add goals. PURPOSE: detect regressions where new eval/inspector
# machinery (Phase 3) or archetype loading (Phase 4) crushes the loop
# under weight. NOT a correctness test — whether the app actually works
# is out of scope here; that's what the per-sprint dossier captures.
#
# USES REAL AGENTS. Expect $1–5 in live SDK costs per run. Expect 18–22
# min wall-clock (baseline ~18.4 min; default cap 25 min). Gated behind
# AUTOPILOT_REAL_AGENT_OK=1 to prevent accidental expense.

set -euo pipefail

# ---- gate ----
if [[ "${AUTOPILOT_REAL_AGENT_OK:-}" != "1" ]]; then
  cat <<EOF >&2
Refusing to run — this smoke makes real agent calls that cost real money.

  Expected envelope: \$1–5, ~18–22 min (baseline ~18.4 min; default cap 25 min)
  Requires: uv, git, jq, autopilot on PATH (or via 'uv run')

To proceed:
  AUTOPILOT_REAL_AGENT_OK=1 $0

To stream JSONL events (--verbose) to your terminal as ralph runs:
  AUTOPILOT_REAL_AGENT_OK=1 VERBOSE=1 $0

To override the envelope:
  MAX_WALL_CLOCK_SEC=1800 MAX_COST_USD=10.0 AUTOPILOT_REAL_AGENT_OK=1 $0
EOF
  exit 2
fi

# ---- setup ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SEED_DIR="$SCRIPT_DIR/seed"
BASELINE_FILE="$SCRIPT_DIR/baseline.json"

MAX_WALL_CLOCK_SEC="${MAX_WALL_CLOCK_SEC:-1500}"   # 25 min (baseline 1106s, +~7 min headroom)
MAX_COST_USD="${MAX_COST_USD:-5.0}"

TMPDIR="$(mktemp -d -t cadence-smoke-XXXXXX)"

echo "==> cadence plumbing smoke"
echo "    seed:     $SEED_DIR"
echo "    tmpdir:   $TMPDIR"
echo "    cap:      ${MAX_WALL_CLOCK_SEC}s, \$${MAX_COST_USD}"
echo ""

# Preserve tmpdir for post-mortem; print on exit so operator can inspect.
trap 'echo ""; echo "==> tmpdir preserved for inspection: $TMPDIR"' EXIT

echo "==> seeding"
cp -r "$SEED_DIR/." "$TMPDIR/"
cd "$TMPDIR"
mkdir -p .dev/logs

git init -q
git add -A
git commit -q -m "seed: cadence fastapi starter"

# Per-project config overrides lifted for this run.
cat > .dev/autopilot.toml <<EOF
max_sprints = 4
max_judge_rounds = 2
max_task_attempts = 2
max_cost_per_run_usd = $MAX_COST_USD
agent_call_timeout_sec = 1200
EOF

# ---- run ralph ----
VERBOSE_FLAG=""
if [[ "${VERBOSE:-}" == "1" ]]; then
  echo "==> verbose: streaming JSONL events from ralph to stderr (also tee'd to .dev/logs/ralph-stderr.log)"
  VERBOSE_FLAG="--verbose"
fi

echo "==> running: autopilot ralph"
START_TS=$(date +%s)

set +e
# stderr is tee'd via process substitution: copy to log file AND echo to the
# operator's terminal. Always tee — VERBOSE just controls whether autopilot
# is emitting JSONL events into that stderr stream in the first place.
timeout --signal=TERM --kill-after=30s "$MAX_WALL_CLOCK_SEC" \
  uv run --project "$REPO_ROOT" autopilot $VERBOSE_FLAG ralph \
  2> >(tee .dev/logs/ralph-stderr.log >&2)
RALPH_EXIT=$?
# Give the tee subprocess a beat to flush before we read the log file.
wait 2>/dev/null || true
set -e

END_TS=$(date +%s)
WALL_CLOCK=$((END_TS - START_TS))

# ---- collect signals ----
COST=$(jq -sr '[.[] | select(.event=="agent.call.end") | .cost_usd // 0] | add // 0' \
  .dev/logs/run-*.jsonl 2>/dev/null || echo 0)

SPRINT_COUNT=0
if compgen -G ".dev/sprints/sprint-*" > /dev/null; then
  SPRINT_COUNT=$(find .dev/sprints -maxdepth 1 -type d -name "sprint-*" | wc -l | tr -d ' ')
fi

echo ""
echo "==> results"
echo "    ralph exit:  $RALPH_EXIT"
echo "    wall clock:  ${WALL_CLOCK}s"
echo "    cost:        \$${COST}"
echo "    sprints:     $SPRINT_COUNT"
echo "    tmp dir:     $TMPDIR"
echo ""

# ---- plumbing assertions ----
FAIL=0

# 1. Ralph must exit cleanly. Anything non-zero is a failure — that
#    includes timeouts (124), SIGKILL (137), SIGTERM from manual kill
#    (143), and any orchestrator-raised CLIError (1). A non-zero exit
#    means the run did not complete and must not be used as a baseline.
if [[ "$RALPH_EXIT" != "0" ]]; then
  case "$RALPH_EXIT" in
    124) echo "FAIL: ralph timed out (exit 124 from timeout(1))" ;;
    137) echo "FAIL: ralph SIGKILL'd (exit 137)" ;;
    143) echo "FAIL: ralph SIGTERM'd (exit 143)" ;;
    *)   echo "FAIL: ralph exited non-zero (exit $RALPH_EXIT)" ;;
  esac
  FAIL=1
fi

# 2. At least one sprint dir produced. Ralph may exit on any outcome —
#    what matters is that it produced *some* state, not that it achieved
#    goals.
if [[ "$SPRINT_COUNT" -lt 1 ]]; then
  echo "FAIL: no sprint directories produced"
  FAIL=1
fi

# 3. All sprint.md + goal.md files have parseable frontmatter (start
#    with ---).
for f in .dev/sprints/sprint-*/sprint-*.md .dev/goals/*.md; do
  [[ -f "$f" ]] || continue
  if ! head -1 "$f" | grep -q '^---$'; then
    echo "FAIL: malformed frontmatter: $f"
    FAIL=1
  fi
done

# 4. JSONL log files are valid JSONL.
for f in .dev/logs/run-*.jsonl; do
  [[ -f "$f" ]] || continue
  if ! jq -c . < "$f" >/dev/null 2>&1; then
    echo "FAIL: invalid JSONL: $f"
    FAIL=1
  fi
done

# 5. Cost under cap. (autopilot should enforce this itself; assert
#    anyway to catch enforcement regressions.)
if awk -v c="$COST" -v cap="$MAX_COST_USD" 'BEGIN{ exit !(c+0 < cap+0) }'; then
  :
else
  echo "FAIL: cost \$$COST exceeded cap \$$MAX_COST_USD"
  FAIL=1
fi

# ---- baseline capture / compare ----
# IMPORTANT: only compare against an existing baseline. We DO NOT save a
# baseline from a failed run — a failure-baseline contaminates every
# future comparison. Capture is a separate, deliberate step (see §2.2 of
# the handoff: "if FAIL on first run, fix the underlying issue, then
# re-run; PASS captures the baseline").
if [[ -f "$BASELINE_FILE" ]]; then
  BASE_WALLCLOCK=$(jq -r .wall_clock_sec "$BASELINE_FILE")
  BASE_COST=$(jq -r .cost_usd "$BASELINE_FILE")
  BASE_REF=$(jq -r .autopilot_ref "$BASELINE_FILE")
  echo "==> baseline comparison (baseline ref: $BASE_REF)"
  echo "    wall clock:  ${WALL_CLOCK}s  vs baseline ${BASE_WALLCLOCK}s"
  echo "    cost:        \$${COST}  vs baseline \$${BASE_COST}"

  # 6. Cost > 2× baseline is a regression.
  if awk -v c="$COST" -v b="$BASE_COST" 'BEGIN{ exit !(c+0 > (b+0) * 2) }'; then
    echo "FAIL: cost more than 2x baseline"
    FAIL=1
  fi
  # 7. Wall-clock > 2× baseline is a regression.
  if awk -v w="$WALL_CLOCK" -v b="$BASE_WALLCLOCK" 'BEGIN{ exit !(w+0 > (b+0) * 2) }'; then
    echo "FAIL: wall-clock more than 2x baseline"
    FAIL=1
  fi
elif [[ $FAIL -eq 0 ]]; then
  # Only capture a baseline when the run actually passed.
  echo "==> no baseline at $BASELINE_FILE — capturing this PASSING run"
  AUTOPILOT_REF="$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  cat > "$BASELINE_FILE" <<EOF
{
  "captured_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "autopilot_ref": "$AUTOPILOT_REF",
  "ralph_exit": $RALPH_EXIT,
  "wall_clock_sec": $WALL_CLOCK,
  "cost_usd": $COST,
  "sprint_count": $SPRINT_COUNT,
  "notes": "Initial baseline captured from first PASSING run. Delete this file and re-run to recapture."
}
EOF
  echo "    baseline saved."
else
  echo "==> no baseline at $BASELINE_FILE; this run FAILED so not capturing one."
fi

# ---- diagnostics on failure ----
if [[ $FAIL -ne 0 ]]; then
  echo ""
  echo "==> diagnostics ============================================"
  echo ""
  echo "--- last 20 JSONL events ---"
  for f in .dev/logs/run-*.jsonl; do
    [[ -f "$f" ]] || continue
    tail -20 "$f" | jq -c '{ts:(.ts_utc // .ts // "?"), event, role: .role, status: .status, error: .error, cost_usd: .cost_usd, duration_ms: .duration_ms}' 2>/dev/null \
      || tail -20 "$f"
  done
  echo ""
  echo "--- ralph-stderr.log (last 50 lines) ---"
  if [[ -s .dev/logs/ralph-stderr.log ]]; then
    tail -50 .dev/logs/ralph-stderr.log
  else
    echo "(empty — ralph wrote nothing to stderr; re-run with VERBOSE=1 if not already)"
  fi
  echo ""
  echo "--- sprint state ---"
  for f in .dev/sprints/sprint-*/sprint-*.md; do
    [[ -f "$f" ]] || continue
    echo "$f:"
    head -5 "$f" | sed 's/^/    /'
  done
  echo ""
  echo "--- task state ---"
  for f in .dev/sprints/sprint-*/task-*.md; do
    [[ -f "$f" ]] || continue
    echo "$f:"
    head -8 "$f" | grep -E '^(id|status|attempts|summary):' | sed 's/^/    /'
  done
  echo ""
  echo "============================================================"
fi

echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "PASS: cadence plumbing smoke"
  exit 0
else
  echo "FAIL: cadence plumbing smoke"
  exit 1
fi
