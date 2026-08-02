#!/usr/bin/env bash
# Study K.1 — `autopilot study run` end-to-end: 2×2 matrix, signals, report.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
mkdir -p "$DIR/scripts" "$DIR/.dev/fake-agents"

cat > "$DIR/scripts/gen.sh" <<'EOF'
#!/usr/bin/env bash
echo "doc for agent=$1 condition=$2" > "$3/doc.md"
EOF
chmod +x "$DIR/scripts/gen.sh"

cat > "$DIR/scripts/score.py" <<'EOF'
import json, sys, pathlib
cell_dir = pathlib.Path(sys.argv[1])
doc = (cell_dir / "doc.md").read_text()
grounded = 0.9 if "skill-on" in doc else 0.6
json.dump({"groundedness": grounded, "coverage": 0.8, "cost_usd": 0.05},
          open(cell_dir / "scores.json", "w"))
EOF

cat > "$DIR/study.md" <<'EOF'
---
matrix:
  agent: [claude-code, codex]
  condition: [skill-on, skill-off]
repetitions: 1
run: "scripts/gen.sh {agent} {condition} {cell_dir}"
scorer: "python3 scripts/score.py {cell_dir}"
---

Does the fact-extraction skill improve groundedness across agents?
EOF

cat > "$DIR/.dev/fake-agents/study-analyst.txt" <<'EOF'
# Report — study-001

## Summary
Skill-on beats skill-off on both agents.

## Cells
(table)

## Findings
### Skill effect
Evidence: all four cells. Confidence: medium (n=1).

## Caveats
Single repetition.
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot study run "$DIR" --spec "$DIR/study.md" > /dev/null

ST="$DIR/.dev/studies/study-001"
$YQ "$ST/study-001.md" '.status' | grep -qx "completed"
test "$(ls "$ST"/cell-*.md | wc -l | tr -d ' ')" = "4"
$YQ "$ST/cell-claude-code-skill-on-r1.md" '.status' | grep -qx "completed"
$YQ "$ST/cell-claude-code-skill-on-r1.md" '.signals.groundedness' | grep -qx "0.9"
$YQ "$ST/cell-codex-skill-off-r1.md" '.signals.groundedness' | grep -qx "0.6"
test -s "$ST/report.md"
# cost absorbed from scores.json (4 × 0.05)
$YQ "$ST/study-001.md" '.cost_usd' | grep -qx "0.2"

echo "STUDY-BASIC PASS"
