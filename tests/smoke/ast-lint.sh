#!/usr/bin/env bash
# AST lint: pure-core discipline (design §12.3).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
uv run python "$REPO_ROOT/tests/smoke/ast-lint.py"
