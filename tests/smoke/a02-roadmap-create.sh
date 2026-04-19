#!/usr/bin/env bash
# A02 — `autopilot roadmap create` writes roadmap.md + goal files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

# Build a minimal project WITHOUT .dev/roadmap.md — roadmap create will write it.
mkdir -p "$DIR/.dev/fake-agents"
cp "$REPO_ROOT/tests/smoke/fixture/.dev/fake-agents/roadmap.txt" "$DIR/.dev/fake-agents/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot roadmap create "$DIR" > /dev/null

test -f "$DIR/.dev/roadmap.md"
test -f "$DIR/.dev/goals/goal-greet-works.md"
$YQ "$DIR/.dev/roadmap.md" '.archetype' | grep -qx "python-cli"
$YQ "$DIR/.dev/goals/goal-greet-works.md" '.id' | grep -qx "greet-works"
$YQ "$DIR/.dev/goals/goal-greet-works.md" '.status' | grep -qx "pending"

# Case: refuses to overwrite.
set +e
uv run autopilot roadmap create "$DIR" > /dev/null 2> "$DIR/err.log"
RC=$?
set -e
test "$RC" -eq 2
grep -qi "already exists" "$DIR/err.log"

echo "A02 PASS"
