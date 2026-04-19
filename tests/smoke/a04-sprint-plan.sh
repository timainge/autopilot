#!/usr/bin/env bash
# A04 — `autopilot sprint plan` writes a draft sprint (status=planning).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot sprint plan "$DIR" > /dev/null

test -d "$DIR/.dev/sprints/sprint-001"
test -f "$DIR/.dev/sprints/sprint-001/sprint-001.md"
compgen -G "$DIR/.dev/sprints/sprint-001/task-*.md" > /dev/null

# Sprint must be in `planning` — no critic/judge run.
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "planning"
# No revision_rounds yet.
rounds="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds | length')"
test "$rounds" = "0"

echo "A04 PASS"
