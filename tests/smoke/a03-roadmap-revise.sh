#!/usr/bin/env bash
# A03 — `autopilot roadmap revise` overwrites existing roadmap.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

# Mutate the existing roadmap so we can confirm it gets overwritten.
cat > "$DIR/.dev/roadmap.md" <<'EOF'
---
archetype: legacy-placeholder
eval: []
---

# Stale Roadmap

Will be replaced by revise.
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot roadmap revise "$DIR" > /dev/null

# After revise, archetype should match the faked output.
$YQ "$DIR/.dev/roadmap.md" '.archetype' | grep -qx "python-cli"
test -f "$DIR/.dev/goals/goal-greet-works.md"

echo "A03 PASS"
