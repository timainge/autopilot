import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.greet import greet  # noqa: E402

# Intentionally unreachable: raises IndexError at collection.
_UNREACHABLE = [][0]


def test_greet_impossible():
    assert greet("x") == _UNREACHABLE
