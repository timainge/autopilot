"""Data models for autopilot manifests, tasks, and agent configs."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Task:
    id: str
    title: str
    status: str  # pending, done, failed
    depends: list[str] = field(default_factory=list)
    attempts: int = 0
    last_error: str | None = None
    body: str = ""
    line_number: int = 0


@dataclass
class Manifest:
    path: Path
    name: str
    approved: bool = False
    status: str = "pending"
    worktree: bool = False
    branch_prefix: str = "autopilot"
    max_budget_usd: float = 5.0
    max_task_attempts: int = 3
    tasks: list[Task] = field(default_factory=list)
    body: str = ""
    raw: str = ""
    # v2 additions:
    archetype: str | None = None
    goal: str = "launch"          # "launch" | "publish" | "complete"
    strategy: str = ""            # prose body of strategy manifest
    max_sprint_budget_usd: float = 5.0
    validate: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    name: str
    description: str = ""
    system_prompt: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    max_turns: int | None = None
    max_budget_usd: float | None = None
    model: str | None = None


@dataclass
class AgentResult:
    success: bool
    output: str = ""
    error: str | None = None
    cost_usd: float = 0.0


@dataclass
class SprintResult:
    sprint_number: int
    tasks_planned: int
    tasks_completed: int
    tasks_failed: int
    validation_passed: bool
    evaluation: str          # strategist's free-text assessment
    strategy_satisfied: bool
    cost_usd: float = 0.0
