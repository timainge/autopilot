#!/usr/bin/env bash
# K.4 — Experiment + two Laps: save → load → save produces byte-identical files.
set -euo pipefail

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

cd "$(dirname "$0")/../.."

uv run python - "$TMPDIR" <<'PY'
import sys
from pathlib import Path

from autopilot.domain.experiment import Experiment, Lap

tmp = Path(sys.argv[1])


def assert_bytes_equal(a: Path, b: Path, label: str) -> None:
    if a.read_bytes() != b.read_bytes():
        print(f"FAIL: {label} bytes differ", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {label}")


first = tmp / "first" / "exp-001"
second = tmp / "second" / "exp-001"

exp = Experiment(
    id="exp-001",
    mode="tune",
    objective="raise eval pass rate",
    rubric="pass rate >= 0.8 across 3 laps",
    head_branch="main",
)
exp._dir = first
exp._save()

lap1 = Lap(id="lap-001", experiment_id="exp-001", spec="try A", branch="exp/exp-001/lap/lap-001")
lap1._path = first / "lap-001.md"
lap1._save()
lap1.record(
    signals={"eval_pass_rate": 0.7, "notes": "first probe"},
    verdict="iterate",
    reason="directionally right, needs another sample",
    cost_usd=0.12,
)

lap2 = Lap(id="lap-002", experiment_id="exp-001", spec="try A harder")
lap2._path = first / "lap-002.md"
lap2._save()

exp.record_lap(lap1)
exp.record_lap(lap2)
exp.complete(summary="done for roundtrip purposes")

loaded = Experiment.load(first)
loaded._dir = second
second.mkdir(parents=True)
loaded._save()
for lap in loaded.laps:
    lap._path = second / f"{lap.id}.md"
    lap._save()

assert_bytes_equal(first / "exp-001.md", second / "exp-001.md", "Experiment")
assert_bytes_equal(first / "lap-001.md", second / "lap-001.md", "Lap recorded")
assert_bytes_equal(first / "lap-002.md", second / "lap-002.md", "Lap pending")
print("ALL FRINK ROUNDTRIPS PASS")
PY

echo "ROUNDTRIP-FRINK PASS"
