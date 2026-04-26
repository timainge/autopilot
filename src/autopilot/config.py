import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from autopilot.domain.errors import ConfigError

# Single-knob model override — when `AUTOPILOT_MODEL` is set, every role's
# `*_model` field collapses to the same model id. Useful for stress-testing
# prompts on a smaller / faster / cheaper model than the per-role defaults.
_MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}
_MODEL_FIELDS: tuple[str, ...] = (
    "worker_model",
    "planner_model",
    "critic_model",
    "judge_model",
    "evaluator_model",
    "researcher_model",
    "roadmap_writer_model",
)


@dataclass(frozen=True)
class AutopilotConfig:
    # Retry + loop caps
    max_task_attempts: int = 2
    max_judge_rounds: int = 2
    max_judge_parse_retries: int = 2
    max_sprints: int = 10
    max_parallel: int = 1

    # Truncation knobs — operator-visible limits on how much text is carried
    # through into stored summaries / reasoning / prompts.
    task_output_summary_chars: int = 500
    verdict_reasoning_max_chars: int = 2000
    verdict_summary_max_chars: int = 500

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

    env_model = os.environ.get("AUTOPILOT_MODEL")
    if env_model:
        alias = env_model.strip().lower()
        if alias not in _MODEL_ALIASES:
            allowed = sorted(_MODEL_ALIASES)
            raise ConfigError(
                source="env:AUTOPILOT_MODEL",
                reason=f"unknown model alias {env_model!r}; expected one of {allowed}",
            )
        for f in _MODEL_FIELDS:
            merged[f] = _MODEL_ALIASES[alias]

    return AutopilotConfig(project_root=root, **merged)
