#!/usr/bin/env bash
# A07 — `autopilot task run <task-file>` executes one task.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Produce an approved sprint so we have a task to run.
uv run autopilot smithers "$DIR" > /dev/null

# Directly start the sprint so task.start transitions are legal.
# (homer calls sprint.start; task run expects an `approved` or `active` sprint.)
uv run python -c "
from pathlib import Path
from autopilot.domain.sprint import Sprint
s = Sprint.load(Path('$DIR/.dev/sprints/sprint-001'))
if s.status == 'approved':
    s.start()
"

TASK_FILE="$(ls "$DIR/.dev/sprints/sprint-001"/task-*.md | head -1)"
test -n "$TASK_FILE"

uv run autopilot task run "$TASK_FILE" > /dev/null

$YQ "$TASK_FILE" '.status' | grep -qx "completed"
summary="$($YQ "$TASK_FILE" '.summary')"
test "$summary" != "null"
test -n "$summary"

# An EvalRun file should have been written by the shell eval.
compgen -G "$DIR/.dev/eval-runs/evalrun-*.md" > /dev/null

echo "A07 PASS"
