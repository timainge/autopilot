#!/usr/bin/env bash
# A08 — `autopilot task retry <task-file>` resumes a failed task.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture-impossible/." "$DIR/"

# fixture-impossible's task eval fails (`false`). Run homer to drive it to
# status=failed, then retry (using a fixture where it will still fail —
# we're only asserting the retry appended an attempt + remained `failed`).
export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot smithers "$DIR" > /dev/null
set +e
uv run autopilot homer "$DIR" > /dev/null
set -e

TASK_FILE="$(ls "$DIR/.dev/sprints/sprint-001"/task-*.md | head -1)"
$YQ "$TASK_FILE" '.status' | grep -qx "failed"
before="$($YQ "$TASK_FILE" '.attempts | length')"

# task retry — task remains failed (impossible fixture), but attempts grows.
set +e
uv run autopilot task retry "$TASK_FILE" > /dev/null
RC=$?
set -e
# Expected non-zero: task didn't complete.
test "$RC" -ne 0

$YQ "$TASK_FILE" '.status' | grep -qx "failed"
after="$($YQ "$TASK_FILE" '.attempts | length')"
test "$after" -gt "$before"

# Retry of a non-failed task should be rejected with CLIError (exit 2).
# Build a clean sprint whose task is `pending`.
CLEAN="$(mktemp -d)"
trap 'rm -rf "$DIR" "$CLEAN"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$CLEAN/"
export AUTOPILOT_FAKE_AGENT="$CLEAN/.dev/fake-agents"
uv run autopilot smithers "$CLEAN" > /dev/null
CLEAN_TASK="$(ls "$CLEAN/.dev/sprints/sprint-001"/task-*.md | head -1)"
set +e
uv run autopilot task retry "$CLEAN_TASK" > /dev/null 2> "$CLEAN/err.log"
RC=$?
set -e
test "$RC" -eq 2
grep -qi "failed" "$CLEAN/err.log"

echo "A08 PASS"
