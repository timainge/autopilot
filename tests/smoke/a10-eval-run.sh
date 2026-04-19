#!/usr/bin/env bash
# A10 — `autopilot eval run <ref>` executes a shell eval and writes an EvalRun.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run --project $REPO_ROOT python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

# Minimal project with a trivially-passing shell eval at goal scope.
mkdir -p "$DIR/.dev/goals"
cat > "$DIR/.dev/roadmap.md" <<'EOF'
---
archetype: python-cli
eval:
  - type: shell
    run: "true"
---

# Roadmap

Minimal fixture for A10.

## Goals

1. [noop](goals/goal-noop.md)
EOF

cat > "$DIR/.dev/goals/goal-noop.md" <<'EOF'
---
id: noop
priority: 1
status: pending
eval:
  - type: shell
    run: "true"
achieved_by: []
summary: null
---

# Goal: noop

A trivially-passing goal for smoke testing eval run.
EOF

cd "$DIR"

# Case 1: explicit index.
uv run --project "$REPO_ROOT" autopilot eval run 'goal:noop#0' > /dev/null
compgen -G "$DIR/.dev/eval-runs/evalrun-*.md" > /dev/null
RUN_FILE="$(ls "$DIR/.dev/eval-runs"/evalrun-*.md | head -1)"
$YQ "$RUN_FILE" '.status' | grep -qx "passed"

# Case 2: no index → runs all evals on entity.
rm -rf "$DIR/.dev/eval-runs"
uv run --project "$REPO_ROOT" autopilot eval run 'goal:noop' > /dev/null
compgen -G "$DIR/.dev/eval-runs/evalrun-*.md" > /dev/null

# Case 3: roadmap-level eval.
rm -rf "$DIR/.dev/eval-runs"
uv run --project "$REPO_ROOT" autopilot eval run 'roadmap#0' > /dev/null
compgen -G "$DIR/.dev/eval-runs/evalrun-*.md" > /dev/null
RUN_FILE="$(ls "$DIR/.dev/eval-runs"/evalrun-*.md | head -1)"
$YQ "$RUN_FILE" '.status' | grep -qx "passed"

echo "A10 PASS"
