#!/usr/bin/env bash
# K.2 — kill -9 mid-lap leaves legible state; re-run resumes and completes.
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
One decisive lap.

### SIGNALS
```yaml
eval_pass_rate: 0.9
```
EOF
cat > "$DIR/.dev/fake-agents/frink-stop-judge.txt" <<'EOF'
VERDICT: merge
REASON: Signal meets the rubric threshold.
DONE: yes
EOF
cat > "$DIR/.dev/fake-agents/frink-reviewer.txt" <<'EOF'
# Review — exp-001

## Summary
Recovered after a kill.

## Proposals

## No-go (observations that did not yield a proposal)
- none
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Slow the fake agents to open a deterministic kill window mid-lap.
AUTOPILOT_FAKE_DELAY_MS=5000 uv run autopilot frink start "$DIR" --mode=tune \
  --objective="fault smoke" --rubric="pass rate >= 0.8" > /dev/null 2>&1 &
PID=$!
sleep 3
# Kill uv's python child too (see f1-kill-resume.sh).
pkill -9 -P $PID 2>/dev/null || true
kill -9 $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# Experiment file is legible mid-flight.
EXP="$DIR/.dev/experiments/exp-001"
$YQ "$EXP/exp-001.md" '.status' | grep -qx "running"

# Re-run (no delay): resumes the running experiment and completes.
uv run autopilot frink start "$DIR" --mode=tune \
  --objective="fault smoke" --rubric="pass rate >= 0.8" > /dev/null

$YQ "$EXP/exp-001.md" '.status' | grep -qx "completed"
ls "$EXP"/lap-*.md > /dev/null
git -C "$DIR" rev-parse --abbrev-ref HEAD | grep -qx "main"

echo "FRINK-FAULT-KILL PASS"
