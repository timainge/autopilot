#!/usr/bin/env bash
# Suite runner. Default: S1..S5 + roundtrip + strict-parse + project-inference + ast-lint.
#                fault: F1..F3.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-default}"

if [ "$MODE" = "default" ]; then
  TESTS=(
    "tests/smoke/s1-smithers.sh"
    "tests/smoke/s2-homer.sh"
    "tests/smoke/s3-ralph.sh"
    "tests/smoke/s4-failure.sh"
    "tests/smoke/s5-chaining.sh"
    "tests/smoke/a01-research.sh"
    "tests/smoke/a02-roadmap-create.sh"
    "tests/smoke/a03-roadmap-revise.sh"
    "tests/smoke/a04-sprint-plan.sh"
    "tests/smoke/a05-sprint-critique.sh"
    "tests/smoke/a06-sprint-judge.sh"
    "tests/smoke/a07-task-run.sh"
    "tests/smoke/a08-task-retry.sh"
    "tests/smoke/a09-eval-show.sh"
    "tests/smoke/a10-eval-run.sh"
    "tests/smoke/roundtrip.sh"
    "tests/smoke/strict-parse.sh"
    "tests/smoke/project-inference.sh"
    "tests/smoke/ast-lint.sh"
    "tests/smoke/role-alignment.sh"
  )
elif [ "$MODE" = "fault" ]; then
  TESTS=(
    "tests/smoke/f1-kill-resume.sh"
    "tests/smoke/f2-atomic-write.sh"
    "tests/smoke/f3-concurrent.sh"
  )
else
  echo "usage: $0 [default|fault]" >&2
  exit 2
fi

pass=0
fail=0
failures=()
for t in "${TESTS[@]}"; do
  echo "===== $t ====="
  if bash "$t"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failures+=("$t")
  fi
done

echo
echo "===== SUITE SUMMARY ====="
echo "mode: $MODE"
echo "pass: $pass"
echo "fail: $fail"
if [ "$fail" -gt 0 ]; then
  echo "failing tests:"
  for f in "${failures[@]}"; do echo "  - $f"; done
  exit 1
fi
echo "ALL GREEN"
