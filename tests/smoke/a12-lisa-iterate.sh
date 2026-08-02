#!/usr/bin/env bash
# A12 — `autopilot lisa` iterates, hits budget cap, and fast-fails.
#
# (a) INSUFFICIENT then SATISFIED → iteration: 2, exit 0.
# (b) Budget cap (max_cost_per_research_run_usd=0.01) → status stopped, exit 1.
# (c) All-enquiries-fail (researcher fixture missing) → status stopped, exit 1.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR_A="$(mktemp -d)"
DIR_B="$(mktemp -d)"
DIR_C="$(mktemp -d)"
trap 'rm -rf "$DIR_A" "$DIR_B" "$DIR_C"' EXIT

mkdir -p "$DIR_A/.dev/fake-agents"

# Two iterations of decomposer output. Iteration 2 targets the gap.
cat > "$DIR_A/.dev/fake-agents/decomposer-call-1.txt" <<'EOF'
### ENQUIRY: Initial question
Scope.
EOF

cat > "$DIR_A/.dev/fake-agents/decomposer-call-2.txt" <<'EOF'
### ENQUIRY: Followup on missing piece
Targets the gap from iteration 1.
EOF

cat > "$DIR_A/.dev/fake-agents/researcher.txt" <<'EOF'
## Findings

Generic findings reused for every parallel enquiry in this test.

## Sources
- file:src/example.py
EOF

cat > "$DIR_A/.dev/fake-agents/synthesiser.txt" <<'EOF'
# Iterating report

## Summary
Findings consolidated.

## Findings
Body.

## Open Questions
Some pieces still missing.
EOF

# First judge call: INSUFFICIENT. Second: SATISFIED.
cat > "$DIR_A/.dev/fake-agents/research-judge-call-1.txt" <<'EOF'
COVERAGE: INSUFFICIENT

## Gaps
- the missing piece needs more depth
EOF

cat > "$DIR_A/.dev/fake-agents/research-judge-call-2.txt" <<'EOF'
COVERAGE: SATISFIED
EOF

# Sub-case (a): iterate then satisfy.
export AUTOPILOT_FAKE_AGENT="$DIR_A/.dev/fake-agents"
unset AUTOPILOT_FAKE_COST_USD

uv run autopilot lisa "$DIR_A" --brief-text="iterate brief" --slug=iterate-x > /dev/null

RUN_DIR="$DIR_A/.dev/research/iterate-x"
$YQ "$RUN_DIR/run.md" '.status' | grep -qx "satisfied"
$YQ "$RUN_DIR/run.md" '.iteration' | grep -qx "2"
$YQ "$RUN_DIR/enquiry-001.md" '.iteration' | grep -qx "1"
$YQ "$RUN_DIR/enquiry-002.md" '.iteration' | grep -qx "2"
grep -q "no gaps" "$RUN_DIR/gaps.md"

# Sub-case (b): budget cap. Reuse fixtures, but cap the per-research-run budget
# below the per-call cost so the second call trips the budget check.
mkdir -p "$DIR_B/.dev/fake-agents"
cp "$DIR_A/.dev/fake-agents/"*.txt "$DIR_B/.dev/fake-agents/"
cat > "$DIR_B/.dev/autopilot.toml" <<'EOF'
max_cost_per_research_run_usd = 0.01
EOF

export AUTOPILOT_FAKE_AGENT="$DIR_B/.dev/fake-agents"
export AUTOPILOT_FAKE_COST_USD="0.05"

set +e
uv run autopilot lisa "$DIR_B" --brief-text="budget brief" --slug=budget-x > /dev/null 2> "$DIR_B/err.log"
RC=$?
set -e
test "$RC" -ne 0
$YQ "$DIR_B/.dev/research/budget-x/run.md" '.status' | grep -qx "stopped"
grep -qi "budget" "$DIR_B/.dev/research/budget-x/run.md"

unset AUTOPILOT_FAKE_COST_USD

# Sub-case (c): fast-fail when researcher fixture absent.
mkdir -p "$DIR_C/.dev/fake-agents"
cp "$DIR_A/.dev/fake-agents/decomposer-call-1.txt" "$DIR_C/.dev/fake-agents/decomposer.txt"
# Deliberately omit researcher.txt → all enquiries fail → fast-fail.

export AUTOPILOT_FAKE_AGENT="$DIR_C/.dev/fake-agents"

set +e
uv run autopilot lisa "$DIR_C" --brief-text="fail-fast" --slug=fail-x > /dev/null 2> "$DIR_C/err.log"
RC=$?
set -e
test "$RC" -ne 0
$YQ "$DIR_C/.dev/research/fail-x/run.md" '.status' | grep -qx "stopped"

echo "A12 PASS"
