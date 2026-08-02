#!/usr/bin/env bash
# F1 — Kill -9 mid-task, resume completes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot sprint prepare "$DIR" > /dev/null

# Slow the fake-agent so we have a deterministic window to kill inside.
AUTOPILOT_FAKE_DELAY_MS=5000 uv run autopilot sprint execute "$DIR" > /dev/null &
PID=$!
sleep 3    # enough to start a task + stall inside run_agent (fake-delay = 5s)
# Kill uv's python child first — kill -9 on uv alone orphans it, and the
# orphan later writes into the deleted temp dir (stray error after the suite).
pkill -9 -P $PID 2>/dev/null || true
kill -9 $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# All task files must parse (= atomic writes never torn).
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' > /dev/null
done

# Resume — the fake delay is no longer active, so sprint execute completes.
uv run autopilot sprint execute "$DIR" > /dev/null
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "completed"

echo "F1 PASS"
