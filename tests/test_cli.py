"""Subprocess-based smoke tests for the autopilot CLI."""

import subprocess
import sys
from pathlib import Path


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["autopilot", *args], capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Help / version
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_lists_subcommands():
    result = run("--help")
    assert result.returncode == 0
    for sub in ("run", "plan", "research", "roadmap", "portfolio"):
        assert sub in result.stdout


def test_version_exits_zero():
    result = run("--version")
    assert result.returncode == 0


def test_version_output_contains_version():
    result = run("--version")
    assert result.returncode == 0
    assert "0.1.0" in result.stdout + result.stderr


def test_run_help():
    result = run("run", "--help")
    assert result.returncode == 0
    assert "--resume" in result.stdout
    assert "--auto-approve" in result.stdout


def test_plan_help():
    result = run("plan", "--help")
    assert result.returncode == 0
    assert "--context" in result.stdout
    assert "--review" in result.stdout


def test_research_help():
    result = run("research", "--help")
    assert result.returncode == 0


def test_roadmap_help():
    result = run("roadmap", "--help")
    assert result.returncode == 0


def test_portfolio_help():
    result = run("portfolio", "--help")
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Dry-run with empty tmpdir (no agents executed)
# ---------------------------------------------------------------------------


def test_run_dry_run_empty_scan(tmp_path: Path):
    result = run("run", "--dry-run", "--scan", str(tmp_path))
    assert result.returncode == 0


def test_dry_run_no_subcommand_backward_compat(tmp_path: Path):
    """autopilot --dry-run --scan <dir> should inject 'run' and exit 0."""
    result = run("--dry-run", "--scan", str(tmp_path))
    assert result.returncode == 0


def test_scan_no_subcommand_backward_compat(tmp_path: Path):
    """autopilot --scan <dir> (no manifest files) should exit 0."""
    result = run("--scan", str(tmp_path))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_path_without_manifest_no_unrecognized_error(tmp_path: Path):
    """A path with no manifest should not produce 'unrecognized arguments' error."""
    result = run(str(tmp_path))
    combined = result.stdout + result.stderr
    assert "unrecognized" not in combined.lower()


def test_portfolio_no_scan_no_paths_exits_nonzero():
    """autopilot portfolio with no --scan and no paths should exit nonzero."""
    result = run("portfolio")
    assert result.returncode != 0
