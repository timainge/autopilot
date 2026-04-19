#!/usr/bin/env bash
# F2 — Interrupt mid-write, file is legible.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
cp -r "$REPO_ROOT/tests/smoke/fixture/." "$DIR/"

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"
uv run autopilot smithers "$DIR" > /dev/null

# Pre-crash: task files parse.
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' > /dev/null
done

# Trigger a mutation with injected crash. The injection raises SystemExit(137)
# between tmp.write_text and os.replace, so the process exits non-zero.
AUTOPILOT_INJECT_CRASH=atomic_write uv run autopilot homer "$DIR" > /dev/null 2>&1 || true

# All task files remain legible (either old content intact, or new content complete).
for f in "$DIR/.dev/sprints/sprint-001"/task-*.md; do
  $YQ "$f" '.status' > /dev/null
done

# No stray .tmp files.
! compgen -G "$DIR/.dev/sprints/sprint-001/*.tmp" > /dev/null

echo "F2 PASS"
