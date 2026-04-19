import functools
import os
from pathlib import Path

_INJECT_CRASH_ENV = "AUTOPILOT_INJECT_CRASH"


def persists(method):
    """Decorator: run the method, then call self._save() so the entity owns its I/O."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        self._save()
        return result

    return wrapper


def atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via a sibling .tmp file and os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    # Test seam (§12.8): simulate a kill between temp write and rename.
    if os.environ.get(_INJECT_CRASH_ENV) == "atomic_write":
        raise SystemExit(137)
    os.replace(tmp, path)
