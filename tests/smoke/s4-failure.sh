#!/usr/bin/env bash
# S4 — Failure propagates and leaves legible state.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture-impossible/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null
set +e; uv run autopilot homer "$DIR" > /dev/null; RC=$?; set -e
test "$RC" -ne 0

$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' | grep -qx "failed"

FAILED=0
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  if $YQ "$f" '.status' | grep -qx "failed"; then
    FAILED=1
    attempts_len="$($YQ "$f" '.attempts | length')"
    test "$attempts_len" -ge 1
  fi
done
test "$FAILED" -eq 1

FAILED_EVAL=0
for f in "$DIR/.dev/eval-runs"/evalrun-*.md; do
  if $YQ "$f" '.status' | grep -qx "failed"; then
    FAILED_EVAL=1
  fi
done
test "$FAILED_EVAL" -eq 1

echo "S4 PASS"
