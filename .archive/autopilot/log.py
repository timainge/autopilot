"""Logging and status output."""

from datetime import datetime


def log(project: str, message: str, icon: str = "•") -> None:
    """Print timestamped status line."""
    ts = datetime.now().strftime("%H:%M:%S")
    name = project[:30]
    print(f"  [{ts}] [{name}] {icon} {message}")


def log_header(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n  [{ts}] {message}")
    print(f"  {'─' * 60}")
