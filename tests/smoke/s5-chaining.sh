#!/usr/bin/env bash
# S5 — Prior sprint summaries feed the next planner.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture-two-goal/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot ralph "$DIR" > /dev/null

test -d "$DIR/.dev/sprints/sprint-001"
test -d "$DIR/.dev/sprints/sprint-002"

summary1="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.summary')"
test "$summary1" != "null"

$YQ "$DIR/.dev/sprints/sprint-002/sprint-002.md" '.status' \
  | grep -qE "approved|active|completed"

echo "S5 PASS"
