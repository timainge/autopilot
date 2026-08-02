#!/usr/bin/env bash
# K.1 — `autopilot frink start` end-to-end: iterate → iterate → merge+done.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"
echo ".dev/" > "$DIR/.gitignore"
git -C "$DIR" init -q
git -C "$DIR" add -A
git -C "$DIR" commit -qm seed
git -C "$DIR" branch -m main

mkdir -p "$DIR/.dev/fake-agents"
cat > "$DIR/.dev/fake-agents/frink-runner.txt" <<'EOF'
### SPEC
Tuned the planner prompt to demand per-task done criteria.

### SIGNALS
```yaml
sprint_status: completed
eval_pass_rate: 0.85
```
EOF
for i in 1 2; do cat > "$DIR/.dev/fake-agents/frink-stop-judge-call-$i.txt" <<'EOF'
VERDICT: iterate
REASON: Direction plausible; need another sample before a verdict-grade signal.
DONE: no
EOF
done
cat > "$DIR/.dev/fake-agents/frink-stop-judge-call-3.txt" <<'EOF'
VERDICT: merge
REASON: Pass rate stable across three laps, meets the rubric threshold.
DONE: yes
EOF
cat > "$DIR/.dev/fake-agents/frink-reviewer.txt" <<'EOF'
# Review — exp-001

## Summary
Three laps; the prompt tune held at 0.85 pass rate.

## Proposals

### P1 — planner prompt
**Change:** keep the done-criteria demand
**Evidence:** laps 1-3 signals
**Signal strength:** medium

## No-go (observations that did not yield a proposal)
- single fixture only
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot frink start "$DIR" --mode=tune \
  --objective="raise eval pass rate" \
  --rubric="pass rate >= 0.8 sustained across 3 laps" > /dev/null

EXP="$DIR/.dev/experiments/exp-001"
$YQ "$EXP/exp-001.md" '.status' | grep -qx "completed"
test -f "$EXP/lap-001.md"
test -f "$EXP/lap-002.md"
test -f "$EXP/lap-003.md"
test -s "$EXP/review.md"
$YQ "$EXP/exp-001.md" '.summary' | grep -q "stable"
$YQ "$EXP/lap-003.md" '.verdict' | grep -qx "merge"

# J.4: kb/runbooks seeded with a bundled-runbook symlink (fixture archetype: python-cli).
test -L "$EXP/kb/runbooks/python-cli.md"

# Branch lifecycle: merged lap branch deleted; iterate branches survive; head clean.
git -C "$DIR" rev-parse --abbrev-ref HEAD | grep -qx "main"
! git -C "$DIR" branch --list "exp/exp-001/lap/lap-003" | grep -q .

echo "FRINK-BASIC PASS"
