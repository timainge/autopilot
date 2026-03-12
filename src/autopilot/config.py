"""Global and per-project configuration via TOML files."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .log import log

GLOBAL_CONFIG_PATH = Path("~/.config/autopilot/config.toml")
PROJECT_CONFIG_FILENAME = "autopilot.toml"

_DEFAULTS: dict = {
    "scan_root": None,
    "git_user": None,
    "dev_dir": ".dev",
    "manifest_filename": "autopilot.md",
    "summary_filename": "project-summary.md",
    "roadmap_filename": "roadmap.md",
    "portfolio_filename": "portfolio.md",
    "max_budget_usd": 5.0,
    "max_task_attempts": 3,
    "runbooks_path": None,
    "sprint_filename": "sprint.md",
    "sprint_log_filename": "sprint-log.md",
    "max_sprints": 10,
}


@dataclass
class AutopilotConfig:
    scan_root: str | None = None
    git_user: str | None = None
    dev_dir: str = ".dev"
    manifest_filename: str = "autopilot.md"
    summary_filename: str = "project-summary.md"
    roadmap_filename: str = "roadmap.md"
    portfolio_filename: str = "portfolio.md"
    max_budget_usd: float = 5.0
    max_task_attempts: int = 3
    runbooks_path: str | None = None
    sprint_filename: str = "sprint.md"
    sprint_log_filename: str = "sprint-log.md"
    max_sprints: int = 10

    def manifest_path(self, project: Path) -> Path:
        return project / self.dev_dir / self.manifest_filename

    def summary_path(self, project: Path) -> Path:
        return project / self.dev_dir / self.summary_filename

    def roadmap_path(self, project: Path) -> Path:
        return project / self.dev_dir / self.roadmap_filename

    def portfolio_path(self, scan_dir: Path) -> Path:
        return scan_dir / self.dev_dir / self.portfolio_filename

    def sprint_path(self, project: Path) -> Path:
        return project / self.dev_dir / self.sprint_filename

    def sprint_log_path(self, project: Path) -> Path:
        return project / self.dev_dir / self.sprint_log_filename

    def resolve_runbooks_path(self) -> Path | None:
        """Return the configured runbooks dir if it exists, else None."""
        if self.runbooks_path:
            p = Path(self.runbooks_path).expanduser()
            if p.exists():
                return p
        return None

    def archetypes_index_path(self) -> Path | None:
        p = self.resolve_runbooks_path()
        if p:
            idx = p / "archetypes.yaml"
            if idx.exists():
                return idx
        return None


def _load_toml(path: Path, warn_on_error: bool = False) -> dict:
    """Load a TOML file and return its contents as a dict.

    Returns an empty dict if the file doesn't exist or cannot be read.
    Logs a warning (when warn_on_error=True) if the file is malformed.
    """
    try:
        p = path.expanduser().resolve()
        if not p.exists():
            return {}
        with open(p, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError:
        if warn_on_error:
            log("config", f"Malformed config file: {path} — using defaults", "⚠️")
        return {}
    except Exception:
        return {}


def load_config(project_path: Path | str | None = None) -> AutopilotConfig:
    """Load merged config: defaults → global → per-project → (CLI handled by caller)."""
    if isinstance(project_path, str):
        project_path = Path(project_path)

    merged = dict(_DEFAULTS)

    # Global config: warn if malformed (user explicitly created it)
    global_data = _load_toml(GLOBAL_CONFIG_PATH, warn_on_error=True)
    merged.update({k: v for k, v in global_data.items() if k in merged})

    # Per-project config: silent if missing
    if project_path is not None:
        project_data = _load_toml(project_path / PROJECT_CONFIG_FILENAME)
        merged.update({k: v for k, v in project_data.items() if k in merged})

    return AutopilotConfig(**merged)
