#!/usr/bin/env bash
# Stage E smoke: `_find_project_root` walks upward to locate `.dev/roadmap.md`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

mkdir -p "$TMPDIR/.dev"
cat > "$TMPDIR/.dev/roadmap.md" <<'EOF'
---
archetype: python-cli
---

# r
EOF

NESTED="$TMPDIR/a/b/c"
mkdir -p "$NESTED"

# Case 1: resolves to the temp dir from a nested subdirectory.
# Invoke uv from the repo root so the venv resolves, but pass cwd via chdir.
RESOLVED=$(uv run --project "$REPO_ROOT" python -c "
import os
os.chdir('$NESTED')
from autopilot.cli import _find_project_root
print(_find_project_root())
")

EXPECTED="$(cd "$TMPDIR" && pwd -P)"
ACTUAL="$(cd "$RESOLVED" && pwd -P)"
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "FAIL: expected $EXPECTED got $ACTUAL" >&2
    exit 1
fi
echo "OK: resolves from nested subdir"

# Case 2: raises CLIError when no .dev/roadmap.md exists up the tree.
ORPHAN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR" "$ORPHAN"' EXIT

set +e
OUTPUT=$(uv run --project "$REPO_ROOT" python -c "
import os
os.chdir('$ORPHAN')
from autopilot.cli import _find_project_root
from autopilot.domain.errors import CLIError
try:
    _find_project_root()
    print('NO_ERROR')
except CLIError as e:
    print(f'CLI_ERROR: {e}')
" 2>&1)
RC=$?
set -e

if [ $RC -ne 0 ]; then
    echo "FAIL: unexpected nonzero exit: $OUTPUT" >&2
    exit 1
fi
case "$OUTPUT" in
    *CLI_ERROR*) echo "OK: raises CLIError on missing roadmap" ;;
    *) echo "FAIL: expected CLI_ERROR, got: $OUTPUT" >&2; exit 1 ;;
esac

echo "ALL PROJECT INFERENCE TESTS PASS"
