#!/usr/bin/env bash
# A05 — `autopilot sprint critique` appends a revision_round with critic_notes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Seed: produce a planning sprint via the atomic `sprint plan`.
uv run autopilot sprint plan "$DIR" > /dev/null

uv run autopilot sprint critique "$DIR" > /dev/null

rounds="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds | length')"
test "$rounds" = "1"
# critic_notes should be non-empty.
notes="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds[0].critic_notes')"
test -n "$notes"
test "$notes" != "null"

# judge_verdict should be empty (atomic critique does not invoke the judge).
verdict="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.revision_rounds[0].judge_verdict')"
# yq prints empty string (or "") for empty scalar.
test "$verdict" = "" -o "$verdict" = "null"

echo "A05 PASS"
