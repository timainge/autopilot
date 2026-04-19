"""AST lint for the pure-core discipline (design §12.3).

Forbidden in `src/autopilot/domain/` (except domain/eval.py):
  - `import subprocess` or `from subprocess ...`
  - `import httpx` or `from httpx ...`
  - `asyncio.create_subprocess_*` attribute access

Forbidden anywhere except `domain/clock.py`:
  - direct `datetime.now()` without a UTC arg

Carve-out: `domain/eval.py` is the execution primitive — subprocess / asyncio
subprocess calls live there deliberately.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DOMAIN_DIR = Path("src/autopilot/domain")
EVAL_WHITELIST = Path("src/autopilot/domain/eval.py")
CLOCK_WHITELIST = Path("src/autopilot/domain/clock.py")


def _iter_py(root: Path):
    for p in sorted(root.rglob("*.py")):
        yield p


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def _check_domain_file(path: Path, src: str, violations: list[str]) -> None:
    tree = ast.parse(src, filename=str(path))
    is_eval_whitelisted = path.resolve() == EVAL_WHITELIST.resolve()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" and not is_eval_whitelisted:
                    violations.append(f"{_rel(path)}:{node.lineno}: forbidden `import subprocess`")
                if alias.name == "httpx":
                    violations.append(f"{_rel(path)}:{node.lineno}: forbidden `import httpx`")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "subprocess" and not is_eval_whitelisted:
                violations.append(f"{_rel(path)}:{node.lineno}: forbidden `from subprocess`")
            if mod == "httpx":
                violations.append(f"{_rel(path)}:{node.lineno}: forbidden `from httpx`")
        elif isinstance(node, ast.Attribute):
            # Detect asyncio.create_subprocess_shell / _exec attribute access.
            if (
                node.attr.startswith("create_subprocess_")
                and isinstance(node.value, ast.Name)
                and node.value.id == "asyncio"
                and not is_eval_whitelisted
            ):
                violations.append(
                    f"{_rel(path)}:{node.lineno}: forbidden `asyncio.{node.attr}` in domain/"
                )


def _check_any_file_clock(path: Path, src: str, violations: list[str]) -> None:
    if path.resolve() == CLOCK_WHITELIST.resolve():
        return
    tree = ast.parse(src, filename=str(path))
    for node in ast.walk(tree):
        # Match `datetime.now(...)` call — only flag zero-arg calls (naive clock).
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "datetime"
            and len(node.args) == 0
            and not node.keywords
        ):
            violations.append(
                f"{_rel(path)}:{node.lineno}: `datetime.now()` with no UTC arg "
                "(only domain/clock.py may read wall-clock time)"
            )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    import os

    os.chdir(repo_root)

    violations: list[str] = []

    # Scan src/autopilot/domain/ with domain-specific rules.
    for p in _iter_py(DOMAIN_DIR):
        src = p.read_text(encoding="utf-8")
        _check_domain_file(p, src, violations)

    # Scan all of src/autopilot/ for the clock rule.
    for p in _iter_py(Path("src/autopilot")):
        src = p.read_text(encoding="utf-8")
        _check_any_file_clock(p, src, violations)

    if violations:
        print("AST LINT FAILURES:")
        for v in violations:
            print(f"  {v}")
        return 1
    print("AST LINT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
