#!/usr/bin/env bash
# A06 — `autopilot sprint judge` appends a revision_round; approves on READY.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Seed: plan + critique.
uv run autopilot sprint plan "$DIR" > /dev/null
uv run autopilot sprint critique "$DIR" > /dev/null

# Judge (fake judge emits VERDICT: READY) should approve.
uv run autopilot sprint judge "$DIR" > /dev/null

$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "approved"
rounds="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds | length')"
test "$rounds" = "2"
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds[1].judge_verdict' | grep -qx "READY"
# Goal should be marked in-progress as a side effect.
$YQ "$DIR/.dev/goals/goal-greet-works.md" '.status' | grep -qx "in-progress"

echo "A06 PASS"
