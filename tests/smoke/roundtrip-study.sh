#!/usr/bin/env bash
# Study K.3 — Study + Cells: save → load → save produces byte-identical files.
set -euo pipefail

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

cd "$(dirname "$0")/../.."

uv run python - "$TMPDIR" <<'PY'
import sys
from pathlib import Path

from autopilot.domain.study import Cell, Study

tmp = Path(sys.argv[1])


def assert_bytes_equal(a: Path, b: Path, label: str) -> None:
    if a.read_bytes() != b.read_bytes():
        print(f"FAIL: {label} bytes differ", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {label}")


first = tmp / "first" / "study-001"
second = tmp / "second" / "study-001"

study = Study(
    id="study-001",
    objective="does the skill transfer?",
    matrix={"agent": ["claude-code", "codex"], "condition": ["on", "off"]},
    run_cmd="scripts/gen.sh {agent} {condition} {cell_dir}",
    scorer_cmd="python3 score.py {cell_dir}",
    repetitions=2,
)
study._dir = first
study._save()

done = Cell(
    id="claude-code-on-r1",
    study_id="study-001",
    params={"agent": "claude-code", "condition": "on"},
    rep=1,
)
done._path = first / "cell-claude-code-on-r1.md"
done._save()
done.start()
done.complete({"groundedness": 0.9, "coverage": 0.8}, 0.05)

pending = Cell(
    id="codex-off-r2",
    study_id="study-001",
    params={"agent": "codex", "condition": "off"},
    rep=2,
)
pending._path = first / "cell-codex-off-r2.md"
pending._save()

study.add_cost(0.05)
study.complete(summary="roundtrip fixture")

loaded = Study.load(first)
loaded._dir = second
second.mkdir(parents=True)
loaded._save()
for cell in loaded.cells:
    cell._path = second / f"cell-{cell.id}.md"
    cell._save()

assert_bytes_equal(first / "study-001.md", second / "study-001.md", "Study")
assert_bytes_equal(
    first / "cell-claude-code-on-r1.md", second / "cell-claude-code-on-r1.md", "Cell completed"
)
assert_bytes_equal(first / "cell-codex-off-r2.md", second / "cell-codex-off-r2.md", "Cell pending")
print("ALL STUDY ROUNDTRIPS PASS")
PY

echo "ROUNDTRIP-STUDY PASS"
