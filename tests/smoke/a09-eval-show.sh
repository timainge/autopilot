#!/usr/bin/env bash
# A09 — `autopilot eval show <ref>` prints payload as YAML.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

cd "$DIR"

# Goal has an eval[0] shell `pytest tests/test_greet.py -x`.
OUTPUT="$(uv run --project "$REPO_ROOT" autopilot eval show goal:greet-works#0 2>&1)"
echo "$OUTPUT" | grep -q "ref: goal:greet-works#0"
echo "$OUTPUT" | grep -q "type: shell"
echo "$OUTPUT" | grep -q "pytest tests/test_greet.py"

# Missing #<i> → CLIError (exit 2).
set +e
uv run --project "$REPO_ROOT" autopilot eval show goal:greet-works > "$DIR/err.log" 2>&1
RC=$?
set -e
test "$RC" -eq 2

# Bad ref syntax → CLIError.
set +e
uv run --project "$REPO_ROOT" autopilot eval show nonsense > /dev/null 2>&1
RC=$?
set -e
test "$RC" -eq 2

# Roadmap-scoped eval works too (roadmap#0).
uv run --project "$REPO_ROOT" autopilot eval show 'roadmap#0' | grep -q "type: shell"

echo "A09 PASS"
