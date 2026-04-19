import os
from datetime import UTC, datetime

_FIXED_CLOCK_ENV = "AUTOPILOT_FIXED_CLOCK"


def now() -> datetime:
    """UTC-aware current time. Honours AUTOPILOT_FIXED_CLOCK for deterministic tests."""
    fixed = os.environ.get(_FIXED_CLOCK_ENV)
    if fixed:
        # Accept trailing Z as UTC designator (fromisoformat in 3.11 handles Z).
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    return datetime.now(UTC)
