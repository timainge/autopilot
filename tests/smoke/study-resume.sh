#!/usr/bin/env bash
# Study K.2 — a failed cell stops the study (exit 1); re-run with the fix
# resumes the same study and re-runs only the non-completed cells.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
mkdir -p "$DIR/scripts" "$DIR/.dev/fake-agents"

cat > "$DIR/scripts/gen.sh" <<'EOF'
#!/usr/bin/env bash
echo "$1" >> run-count.txt
echo "doc $1" > "$2/doc.md"
EOF
chmod +x "$DIR/scripts/gen.sh"

# Scorer fails for codex until fixed.txt exists.
cat > "$DIR/scripts/score.py" <<'EOF'
import json, sys, pathlib
cell_dir = pathlib.Path(sys.argv[1]); agent = sys.argv[2]
if agent == "codex" and not pathlib.Path("fixed.txt").exists():
    sys.exit(3)
json.dump({"groundedness": 0.8}, open(cell_dir / "scores.json", "w"))
EOF

cat > "$DIR/study.md" <<'EOF'
---
matrix:
  agent: [claude-code, codex]
run: "scripts/gen.sh {agent} {cell_dir}"
scorer: "python3 scripts/score.py {cell_dir} {agent}"
---

Resume semantics check.
EOF

cat > "$DIR/.dev/fake-agents/study-analyst.txt" <<'EOF'
# Report — study-001

## Summary
ok

## Cells
(table)

## Findings
(none)

## Caveats
(none)
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

# First run: codex cell fails → study stopped, exit 1.
set +e
uv run autopilot study run "$DIR" --spec "$DIR/study.md" > /dev/null
RC=$?
set -e
test "$RC" -eq 1
ST="$DIR/.dev/studies/study-001"
$YQ "$ST/study-001.md" '.status' | grep -qx "stopped"
$YQ "$ST/cell-codex-r1.md" '.status' | grep -qx "failed"
$YQ "$ST/cell-claude-code-r1.md" '.status' | grep -qx "completed"
test "$(wc -l < "$DIR/run-count.txt" | tr -d ' ')" = "2"

# Fix, re-run: same study resumes; only the failed cell re-runs.
touch "$DIR/fixed.txt"
uv run autopilot study run "$DIR" --spec "$DIR/study.md" > /dev/null
$YQ "$ST/study-001.md" '.status' | grep -qx "completed"
$YQ "$ST/cell-codex-r1.md" '.status' | grep -qx "completed"
test "$(wc -l < "$DIR/run-count.txt" | tr -d ' ')" = "3"
test ! -d "$DIR/.dev/studies/study-002"

echo "STUDY-RESUME PASS"
