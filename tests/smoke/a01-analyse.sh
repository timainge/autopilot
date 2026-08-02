#!/usr/bin/env bash
# A01 — `autopilot analyse` writes .dev/analysis/<topic>.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Case 1: default topic.
uv run autopilot analyse "$DIR" > /dev/null
test -f "$DIR/.dev/analysis/general.md"
grep -q "Research Notes" "$DIR/.dev/analysis/general.md"

# Case 2: explicit topic.
uv run autopilot analyse "$DIR" --topic=auth > /dev/null
test -f "$DIR/.dev/analysis/auth.md"
grep -q "Research Notes" "$DIR/.dev/analysis/auth.md"

echo "A01 PASS"
