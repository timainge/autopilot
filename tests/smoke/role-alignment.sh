#!/usr/bin/env bash
# Role-alignment lint (phase-2.md §2.3).
#
# Every `src/autopilot/agents/roles/*.md` must satisfy ONE of:
#   (A) a `run_agent("<role>", ...)` call site in `src/autopilot/`, OR
#   (B) referenced in `.dev/workflows.md` (§4.1 matrix or §5 loops).
#
# Inverse: every `run_agent("<role>", ...)` call site has a matching
# `roles/<role>.md` file. No orphans on either side.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

ROLES_DIR="src/autopilot/agents/roles"
WORKFLOWS="/dev/null"
if [ -f ".dev/workflows.md" ]; then
  WORKFLOWS=".dev/workflows.md"
fi

FAIL=0

# Forward check: each role file is invoked OR documented.
for f in "$ROLES_DIR"/*.md; do
  role=$(basename "$f" .md)

  # (A) call site — match across lines (role literal may be on next line).
  has_call_site=0
  if grep -rlE --include='*.py' "run_agent\(" src/autopilot \
       --exclude-dir=roles >/dev/null 2>&1; then
    # Pull the first arg (possibly on next line) and compare.
    if python3 - "$role" <<'PY' >/dev/null 2>&1
import re, sys, pathlib
role = sys.argv[1]
pat = re.compile(r"run_agent\(\s*['\"]([a-z-]+)['\"]")
for p in pathlib.Path("src/autopilot").rglob("*.py"):
    if "roles" in p.parts:
        continue
    for m in pat.finditer(p.read_text()):
        if m.group(1) == role:
            sys.exit(0)
sys.exit(1)
PY
    then
      has_call_site=1
    fi
  fi

  # (B) workflows.md reference.
  has_doc=0
  if grep -qi "$role" "$WORKFLOWS"; then
    has_doc=1
  fi

  if [ "$has_call_site" -eq 0 ] && [ "$has_doc" -eq 0 ]; then
    echo "ORPHAN ROLE: $role — no run_agent() call site and not referenced in workflows.md"
    FAIL=1
  fi
done

# Inverse check: each call site has a role file.
while IFS= read -r role; do
  [ -z "$role" ] && continue
  if [ ! -f "$ROLES_DIR/${role}.md" ]; then
    echo "MISSING ROLE FILE: run_agent(\"$role\", ...) has no roles/${role}.md"
    FAIL=1
  fi
done < <(python3 - <<'PY'
import re, pathlib
pat = re.compile(r"run_agent\(\s*['\"]([a-z-]+)['\"]")
seen = set()
for p in pathlib.Path("src/autopilot").rglob("*.py"):
    if "roles" in p.parts:
        continue
    for m in pat.finditer(p.read_text()):
        seen.add(m.group(1))
for r in sorted(seen):
    print(r)
PY
)

if [ "$FAIL" -eq 1 ]; then
  echo "ROLE-ALIGNMENT FAIL"
  exit 1
fi
echo "ROLE-ALIGNMENT PASS"
