#!/usr/bin/env bash
# S3 — `ralph` terminates on goal achievement.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot ralph "$DIR" > /dev/null

test "$(ls "$DIR/.dev/sprints/" | wc -l | tr -d ' ')" -ge 1

$YQ "$DIR/.dev/goals/goal-greet-works.md" '.status' | grep -qx "achieved"
$YQ "$DIR/.dev/goals/goal-greet-works.md" '.achieved_by[0]' | grep -qx "sprint-001"
summary="$($YQ "$DIR/.dev/goals/goal-greet-works.md" '.summary')"
test "$summary" != "null"

echo "S3 PASS"
