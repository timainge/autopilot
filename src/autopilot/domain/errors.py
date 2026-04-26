from dataclasses import dataclass
from pathlib import Path


# eq=False so exceptions retain identity-based equality (Exception default).
@dataclass(eq=False)
class ValidationError(Exception):
    entity_type: str
    entity_id: str | None
    field: str | None
    reason: str

    def __str__(self) -> str:
        loc = f"{self.entity_type}"
        if self.entity_id:
            loc += f"[{self.entity_id}]"
        if self.field:
            loc += f".{self.field}"
        return f"ValidationError: {loc}: {self.reason}"


@dataclass(eq=False)
class InvalidTransition(Exception):  # noqa: N818 — name fixed by design §12.2
    entity_type: str
    entity_id: str | None
    current_status: str
    attempted_transition: str

    def __str__(self) -> str:
        eid = f"[{self.entity_id}]" if self.entity_id else ""
        return (
            f"InvalidTransition: {self.entity_type}{eid}: cannot "
            f"{self.attempted_transition} from status={self.current_status}"
        )


@dataclass(eq=False)
class ParseError(Exception):
    file_path: Path
    line_number: int | None
    reason: str

    def __str__(self) -> str:
        loc = str(self.file_path)
        if self.line_number is not None:
            loc += f":{self.line_number}"
        return f"ParseError: {loc}: {self.reason}"


@dataclass(eq=False)
class EvalFileNotFound(Exception):  # noqa: N818 — name fixed by design §12.2
    eval_ref: str
    missing_path: Path

    def __str__(self) -> str:
        return f"EvalFileNotFound: {self.eval_ref}: missing file {self.missing_path}"


@dataclass(eq=False)
class JudgeModelCollision(Exception):  # noqa: N818 — name fixed by design §12.2
    judge_model: str
    worker_model: str

    def __str__(self) -> str:
        return (
            f"JudgeModelCollision: judge_model={self.judge_model} "
            f"must differ from worker_model={self.worker_model}"
        )


@dataclass(eq=False)
class BudgetExceeded(Exception):  # noqa: N818 — name fixed by design §12.2
    scope: str  # "per_call" | "per_run"
    limit_usd: float
    actual_usd: float

    def __str__(self) -> str:
        return (
            f"BudgetExceeded: scope={self.scope} limit=${self.limit_usd:.2f} "
            f"actual=${self.actual_usd:.2f}"
        )


@dataclass(eq=False)
class ConfigError(Exception):
    source: str  # file path or "code"
    reason: str

    def __str__(self) -> str:
        return f"ConfigError: {self.source}: {self.reason}"


@dataclass(eq=False)
class EvalInfrastructureError(Exception):  # noqa: N818 — name fixed by design §12.2
    eval_ref: str
    reason: str

    def __str__(self) -> str:
        return f"EvalInfrastructureError: {self.eval_ref}: {self.reason}"


@dataclass(eq=False)
class SprintEvaluatorError(Exception):  # noqa: N818 — name fixed by design §12.2
    sprint_id: str
    reason: str

    def __str__(self) -> str:
        return f"SprintEvaluatorError: {self.sprint_id}: {self.reason}"


@dataclass(eq=False)
class CLIError(Exception):
    reason: str

    def __str__(self) -> str:
        return f"CLIError: {self.reason}"
