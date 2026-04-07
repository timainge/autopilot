"""Subprocess-based smoke tests for the autopilot CLI."""

import subprocess
from pathlib import Path


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "autopilot", *args], capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Help / version
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_lists_subcommands():
    result = run("--help")
    assert result.returncode == 0
    for sub in ("sprint", "plan", "roadmap", "portfolio", "build", "ralph"):
        assert sub in result.stdout


def test_version_exits_zero():
    result = run("--version")
    assert result.returncode == 0


def test_version_output_contains_version():
    result = run("--version")
    assert result.returncode == 0
    assert "0.2.0" in result.stdout + result.stderr


def test_sprint_help():
    result = run("sprint", "--help")
    assert result.returncode == 0
    assert "--resume" in result.stdout
    assert "--auto-approve" in result.stdout


def test_plan_help():
    result = run("plan", "--help")
    assert result.returncode == 0
    assert "--context" in result.stdout


def test_roadmap_help():
    result = run("roadmap", "--help")
    assert result.returncode == 0


def test_portfolio_help():
    result = run("portfolio", "--help")
    assert result.returncode == 0


def test_build_help():
    result = run("build", "--help")
    assert result.returncode == 0


def test_ralph_help():
    result = run("ralph", "--help")
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Dry-run with empty tmpdir (no agents executed)
# ---------------------------------------------------------------------------


def test_sprint_dry_run_empty_scan(tmp_path: Path):
    result = run("sprint", "--dry-run", "--scan", str(tmp_path))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_portfolio_no_scan_no_paths_exits_nonzero():
    """autopilot portfolio with no --scan and no paths should exit nonzero."""
    result = run("portfolio")
    assert result.returncode != 0
