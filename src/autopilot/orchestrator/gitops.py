"""Async git helpers for the Frink lap-branch lifecycle.

Kept out of orchestrator/frink.py so the loop itself stays free of
subprocess use (phase-5-frink.md §14.3); this module is the one place
Frink touches git.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(eq=False)
class GitOpsError(Exception):
    command: str
    output: str

    def __str__(self) -> str:
        return f"GitOpsError: `git {self.command}` failed: {self.output.strip()}"


async def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    out = out_b.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise GitOpsError(command=" ".join(args), output=out)
    return out


async def current_branch(repo: Path) -> str:
    return (await _git(repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()


async def branch_exists(repo: Path, name: str) -> bool:
    out = await _git(repo, "branch", "--list", name)
    return bool(out.strip())


async def create_and_checkout(repo: Path, name: str, start_point: str) -> None:
    await _git(repo, "checkout", "-b", name, start_point)


async def checkout(repo: Path, ref: str) -> None:
    await _git(repo, "checkout", ref)


async def merge_no_ff(repo: Path, branch: str, message: str) -> None:
    await _git(repo, "merge", "--no-ff", branch, "-m", message)


async def delete_branch(repo: Path, name: str) -> None:
    await _git(repo, "branch", "-D", name)


async def commit_all_if_dirty(repo: Path, message: str) -> None:
    """Commit any uncommitted lap work so branch switches never carry changes.

    `.dev/` is excluded: it is live orchestration state, not lap work —
    sweeping it onto a lap branch would make checkout rip it back out.
    """
    status = await _git(repo, "status", "--porcelain", "--", ":(exclude).dev")
    if not status.strip():
        return
    await _git(repo, "add", "-A", "--", ":(exclude).dev")
    await _git(repo, "commit", "-m", message)


async def tracked_under(repo: Path, path: str) -> bool:
    out = await _git(repo, "ls-files", "--", path)
    return bool(out.strip())
