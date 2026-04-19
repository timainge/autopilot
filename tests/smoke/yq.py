"""Minimal `yq -f extract` replacement. Reads a markdown file's YAML frontmatter
and prints the value at a dotted path.

usage: python yq.py <file> <dotted-path>

Supported path forms:
  .key               → top-level scalar
  .key.sub           → nested scalar
  .key[N]            → list index
  .key | length      → list length
  .key[N].sub        → nested field of list element
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit(f"{path}: no frontmatter")
    lines = text.splitlines()
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            close_idx = i
            break
    if close_idx is None:
        raise SystemExit(f"{path}: unclosed frontmatter")
    yaml_text = "\n".join(lines[1:close_idx])
    data = yaml.safe_load(yaml_text) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: frontmatter is not a mapping")
    return data


_TOKEN_RE = re.compile(r"\.(?P<key>[A-Za-z_][A-Za-z_0-9-]*)(?P<idx>\[\d+\])?")


def _walk(data, path_str: str):
    # Handle "| length" suffix.
    length_mode = False
    if "|" in path_str:
        left, right = path_str.split("|", 1)
        path_str = left.strip()
        if right.strip() != "length":
            raise SystemExit(f"unsupported pipeline: {right.strip()}")
        length_mode = True

    current = data
    pos = 0
    if not path_str.startswith("."):
        raise SystemExit(f"path must start with '.': {path_str}")
    while pos < len(path_str):
        m = _TOKEN_RE.match(path_str, pos)
        if not m:
            raise SystemExit(f"cannot parse path at pos {pos}: {path_str}")
        key = m.group("key")
        idx = m.group("idx")
        if not isinstance(current, dict):
            raise SystemExit(f"path seeks key '{key}' in non-mapping: {type(current).__name__}")
        current = current.get(key)
        if idx is not None:
            i = int(idx[1:-1])
            if not isinstance(current, list):
                raise SystemExit(f"path seeks [{i}] in non-list: {type(current).__name__}")
            if i >= len(current):
                # yq prints empty on out-of-range index; mirror that.
                current = None
            else:
                current = current[i]
        pos = m.end()

    if length_mode:
        if current is None:
            print(0)
            return
        if isinstance(current, list | dict | str):
            print(len(current))
            return
        raise SystemExit(f"length: unsupported type {type(current).__name__}")

    # Mirror yq `-f extract` output: null for None, scalar otherwise; empty for missing.
    if current is None:
        print("null")
    elif isinstance(current, bool):
        print("true" if current else "false")
    else:
        print(current)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: yq.py <file> <dotted-path>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"{path}: not a file", file=sys.stderr)
        return 2
    data = _read_frontmatter(path)
    _walk(data, argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
