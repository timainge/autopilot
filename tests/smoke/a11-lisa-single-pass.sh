#!/usr/bin/env bash
# A11 — `autopilot lisa` single-pass: SATISFIED on iteration 1.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
YQ="uv run python $REPO_ROOT/tests/smoke/yq.py"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

mkdir -p "$DIR/.dev/fake-agents"

cat > "$DIR/.dev/fake-agents/decomposer.txt" <<'EOF'
### ENQUIRY: How does X work?
Look at the code paths.

### ENQUIRY: What configures X?
Find the relevant settings.
EOF

cat > "$DIR/.dev/fake-agents/researcher.txt" <<'EOF'
## Findings

X is a fake construct used by the smoke harness. Researchers run in
parallel and each writes findings like this one.

## Sources
- file:src/example.py
EOF

cat > "$DIR/.dev/fake-agents/synthesiser.txt" <<'EOF'
# Test report

## Summary
Two enquiries answered. Coverage is good for the test brief.

## Findings
Findings from the parallel researchers, synthesised into one place.

## Open Questions
None for this fixture.
EOF

cat > "$DIR/.dev/fake-agents/research-judge.txt" <<'EOF'
COVERAGE: SATISFIED
EOF

export AUTOPILOT_FAKE_AGENT="$DIR/.dev/fake-agents"

uv run autopilot lisa "$DIR" --brief-text="What is X in the test fixture?" --slug=test-x > /dev/null

RUN_DIR="$DIR/.dev/research/test-x"

test -f "$RUN_DIR/run.md"
test -f "$RUN_DIR/plan.md"
test -f "$RUN_DIR/report.md"
test -f "$RUN_DIR/summary.md"
test -f "$RUN_DIR/gaps.md"

# At least one completed enquiry file.
ls "$RUN_DIR"/enquiry-*.md > /dev/null

$YQ "$RUN_DIR/run.md" '.status' | grep -qx "satisfied"
$YQ "$RUN_DIR/run.md" '.iteration' | grep -qx "1"

# Non-empty report and summary.
test -s "$RUN_DIR/report.md"
test -s "$RUN_DIR/summary.md"

echo "A11 PASS"
