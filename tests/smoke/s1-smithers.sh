#!/usr/bin/env bash
# S1 — `smithers` produces a valid sprint directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null

test -d "$DIR/.dev/sprints/sprint-001"
test -f "$DIR/.dev/sprints/sprint-001/sprint-001.md"
compgen -G "$DIR/.dev/sprints/sprint-001/task-*.md" > /dev/null

$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "approved"
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.primary_goal' | grep -qx "greet-works"
$YQ "$DIR/.dev/goals/goal-greet-works.md" '.status' | grep -qx "in-progress"

for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' | grep -qx "pending"
  test -n "$(sed -n '/^---$/,/^---$/!p' "$f" | head -5)"
done

echo "S1 PASS"
