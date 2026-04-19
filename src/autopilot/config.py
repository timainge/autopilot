import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from autopilot.domain.errors import ConfigError


@dataclass(frozen=True)
class AutopilotConfig:
    # Retry + loop caps
    max_task_attempts: int = 2
    max_judge_rounds: int = 2
    max_sprints: int = 10
    max_parallel: int = 1

    # Timeouts
    eval_shell_timeout_sec: int = 120
    agent_call_timeout_sec: int = 600

    # Models
    worker_model: str = "claude-sonnet-4-6"
    planner_model: str = "claude-opus-4-7"
    critic_model: str = "claude-sonnet-4-6"
    judge_model: str = "claude-sonnet-4-6"
    evaluator_model: str = "claude-sonnet-4-6"
    researcher_model: str = "claude-sonnet-4-6"
    roadmap_writer_model: str = "claude-opus-4-7"

    # Budget
    max_cost_per_call_usd: float = 2.00
    max_cost_per_run_usd: float = 50.00

    # Paths (computed post-resolution, not user-set)
    project_root: Path = field(default_factory=Path.cwd)


def load_config(project_root: Path | None = None) -> AutopilotConfig:
    """Layer config: defaults < ~/.config/autopilot/config.toml < <project>/.dev/autopilot.toml."""
    root = project_root if project_root is not None else Path.cwd()
    known = {f.name for f in fields(AutopilotConfig)}
    merged: dict[str, object] = {}
    for path in [
        Path.home() / ".config" / "autopilot" / "config.toml",
        root / ".dev" / "autopilot.toml",
    ]:
        if not path.exists():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(source=str(path), reason=f"invalid TOML: {e}") from e
        unknown = set(data) - known
        if unknown:
            raise ConfigError(
                source=str(path),
                reason=f"unknown config keys: {sorted(unknown)}",
            )
        if "project_root" in data:
            raise ConfigError(
                source=str(path),
                reason="project_root is not user-settable",
            )
        merged.update(data)
    return AutopilotConfig(project_root=root, **merged)
