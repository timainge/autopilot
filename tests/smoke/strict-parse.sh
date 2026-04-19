#!/usr/bin/env bash
# Stage C smoke: §12.9 strict parsing. Unknown keys and missing required fields
# must raise ParseError — never be silently accepted.
set -euo pipefail

cd "$(dirname "$0")/../.."

uv run python - <<'PY'
import sys

from autopilot.domain.errors import ParseError
from autopilot.domain.parse import parse_goal, parse_sprint, parse_task

failures: list[str] = []


def expect_parse_error(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except ParseError as e:
        print(f"OK: {label} raised ParseError: {e}")
        return
    except Exception as e:
        failures.append(f"{label}: wrong exception type {type(e).__name__}: {e}")
        return
    failures.append(f"{label}: did not raise")


# 1. Unknown top-level key in task frontmatter.
expect_parse_error(
    "task unknown key",
    parse_task,
    """---
id: 001
status: pending
wobble: true
---

# Task 001

body
""",
)

# 2. Missing required `id` in task frontmatter.
expect_parse_error(
    "task missing id",
    parse_task,
    """---
status: pending
---

# Task

body
""",
)

# 3. Unknown key in sprint frontmatter.
expect_parse_error(
    "sprint unknown key",
    parse_sprint,
    """---
id: sprint-001
primary_goal: g1
status: approved
bogus: yes
---

body
""",
    [
        """---
id: 001
status: pending
---

body
"""
    ],
)

# 4. Unknown key in goal frontmatter.
expect_parse_error(
    "goal unknown key",
    parse_goal,
    """---
id: g1
priority: 1
unexpected: x
---

body
""",
)

if failures:
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    sys.exit(1)
print("ALL STRICT PARSE CHECKS PASS")
PY
