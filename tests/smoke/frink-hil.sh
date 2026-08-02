#!/usr/bin/env bash
# K.3 — HIL gate: pending file written; deleting it accepts the proposed verdict.
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
REASON: Signal meets the rubric threshold on the first lap.
DONE: yes
EOF
cat > "$DIR/.dev/fake-agents/frink-reviewer.txt" <<'EOF'
# Review — exp-001

## Summary
One lap, merged.

## Proposals

## No-go (observations that did not yield a proposal)
- single lap
EOF

# Fast HIL polling so the test doesn't sit on the default 5s interval.
printf 'frink_hil_poll_sec = 1\n' > "$DIR/.dev/autopilot.toml"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot frink start "$DIR" --mode=tune --hil \
  --objective="hil smoke" --rubric="pass rate >= 0.8" > /dev/null &
PID=$!

# Wait for the pending file, then simulate the human accepting by deleting it.
PENDING="$DIR/.dev/experiments/exp-001/lap-001.pending.md"
for _ in $(seq 1 60); do
  [ -f "$PENDING" ] && break
  sleep 0.5
done
test -f "$PENDING"
grep -q "proposed_verdict: merge" "$PENDING"
rm "$PENDING"

wait $PID

EXP="$DIR/.dev/experiments/exp-001"
$YQ "$EXP/exp-001.md" '.status' | grep -qx "completed"
$YQ "$EXP/lap-001.md" '.verdict' | grep -qx "merge"
test ! -f "$PENDING"

echo "FRINK-HIL PASS"
