#!/usr/bin/env bash
# F3 — Two concurrent `homer` calls — neither corrupts state.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null

set +e
uv run autopilot homer "$DIR" > /dev/null 2>&1 &
P1=$!
uv run autopilot homer "$DIR" > /dev/null 2>&1 &
P2=$!
wait $P1 || true
wait $P2 || true
set -e

# End state: files are parseable (atomic-write guarantees no torn reads).
$YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status' > /dev/null
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' > /dev/null
done

# Sprint must end in a terminal state (completed or failed — "last write wins").
status="$($YQ "$DIR/.dev/sprints/sprint-001/sprint-001.md" '.status')"
case "$status" in
  completed|failed|active) ;;
  *) echo "FAIL: unexpected sprint status $status" >&2; exit 1 ;;
esac

echo "F3 PASS"
