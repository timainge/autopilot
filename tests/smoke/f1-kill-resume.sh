#!/usr/bin/env bash
# F1 — Kill -9 mid-task, resume completes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null

# Slow the fake-agent so we have a deterministic window to kill inside.
AUTOPILOT_FAKE_DELAY_MS=5000 uv run autopilot homer "$DIR" > /dev/null &
PID=$!
sleep 3    # enough to start a task + stall inside run_agent (fake-delay = 5s)
kill -9 $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# All task files must parse (= atomic writes never torn).
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' > /dev/null
done

# Resume — the fake delay is no longer active, so homer completes.
uv run autopilot homer "$DIR" > /dev/null
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "completed"

echo "F1 PASS"
