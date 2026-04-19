#!/usr/bin/env bash
# A01 — `autopilot research` writes .dev/research/<topic>.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# Case 1: default topic.
uv run autopilot research "$DIR" > /dev/null
test -f "$DIR/.dev/research/general.md"
grep -q "Research Notes" "$DIR/.dev/research/general.md"

# Case 2: explicit topic.
uv run autopilot research "$DIR" --topic=auth > /dev/null
test -f "$DIR/.dev/research/auth.md"
grep -q "Research Notes" "$DIR/.dev/research/auth.md"

echo "A01 PASS"
