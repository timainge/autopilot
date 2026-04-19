import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.greet import greet  # noqa: E402


def test_greet_world():
    assert greet("world") == "Hello, world!"
