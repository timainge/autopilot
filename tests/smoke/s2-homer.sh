#!/usr/bin/env bash
# S2 — `homer` executes tasks to completion.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null
uv run autopilot homer "$DIR" > /dev/null

$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "completed"

for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' | grep -qx "completed"
  summary="$($YQ "$f" '.summary')"
  test "$summary" != "null"
done

compgen -G "$DIR/.dev/eval-runs/evalrun-*.md" > /dev/null

# Fixture's src/greet.py is already correct; this proves the eval loop ran.
grep -q "Hello," "$DIR/src/greet.py"

echo "S2 PASS"
