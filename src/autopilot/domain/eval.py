import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.domain.clock import now
from autopilot.domain.errors import (
    EvalFileNotFound,
    InvalidTransition,
    JudgeModelCollision,
    ValidationError,
)
from autopilot.domain.ids import EvalRef, EvalRunId
from autopilot.domain.persists import atomic_write, persists
from autopilot.log import emit


@dataclass
class Eval:
    """Value object: one eval definition embedded in a containing entity's frontmatter."""

    type: Literal["shell", "judge", "metric"]

    # shell
    run: str | None = None
    script: str | None = None
    timeout_sec: int = 120

    # judge
    prompt: str | None = None
    prompt_file: str | None = None
    judge_model: str = "claude-sonnet-4-6"
    rounds: int = 1

    # metric (deferred execution; shape encoded now)
    threshold: float | None = None
    weight: float | None = None

    # selection
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        match self.type:
            case "shell":
                if bool(self.run) == bool(self.script):
                    raise ValidationError(
                        entity_type="eval",
                        entity_id=None,
                        field="run/script",
                        reason="shell eval requires exactly one of run/script",
                    )
            case "judge":
                if bool(self.prompt) == bool(self.prompt_file):
                    raise ValidationError(
                        entity_type="eval",
                        entity_id=None,
                        field="prompt/prompt_file",
                        reason="judge eval requires exactly one of prompt/prompt_file",
                    )
            case "metric":
                if not self.script or self.threshold is None:
                    raise ValidationError(
                        entity_type="eval",
                        entity_id=None,
                        field="script/threshold",
                        reason="metric eval requires script + threshold",
                    )
                if self.weight is not None and not 0 <= self.weight <= 1:
                    raise ValidationError(
                        entity_type="eval",
                        entity_id=None,
                        field="weight",
                        reason="metric weight must be in [0, 1]",
                    )
            case _:
                raise ValidationError(
                    entity_type="eval",
                    entity_id=None,
                    field="type",
                    reason=f"unknown eval type: {self.type}",
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a YAML-safe dict, omitting fields equal to their defaults."""
        d: dict[str, Any] = {"type": self.type}
        match self.type:
            case "shell":
                if self.run is not None:
                    d["run"] = self.run
                if self.script is not None:
                    d["script"] = self.script
                if self.timeout_sec != 120:
                    d["timeout_sec"] = self.timeout_sec
            case "judge":
                if self.prompt is not None:
                    d["prompt"] = self.prompt
                if self.prompt_file is not None:
                    d["prompt_file"] = self.prompt_file
                if self.judge_model != "claude-sonnet-4-6":
                    d["judge_model"] = self.judge_model
                if self.rounds != 1:
                    d["rounds"] = self.rounds
            case "metric":
                if self.script is not None:
                    d["script"] = self.script
                if self.threshold is not None:
                    d["threshold"] = self.threshold
                if self.weight is not None:
                    d["weight"] = self.weight
        if self.tags:
            d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Eval":
        return cls(**data)


@dataclass
class EvalContext:
    """Payload passed to an eval runner. `entity` is any domain entity, `payload` is a catchall."""

    entity: Any
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalRun:
    """Execution record for one eval invocation. First-class entity with @persists."""

    id: EvalRunId
    eval_ref: EvalRef
    eval_snapshot: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["running", "passed", "failed", "error"] = "running"
    score: float | None = None
    output: str = ""
    cost_usd: float = 0.0
    context_digest: str = ""
    _path: Path | None = None

    @classmethod
    def start(cls, ref: EvalRef, eval_def: Eval, ctx: EvalContext) -> "EvalRun":
        """Create a new run, assign next id-for-today, persist with status=running, return it."""
        project_root = ctx.payload.get("project_root")
        if not isinstance(project_root, Path):
            project_root = Path.cwd()
        eval_runs_dir = project_root / ".dev" / "eval-runs"
        eval_runs_dir.mkdir(parents=True, exist_ok=True)

        today = now().strftime("%Y-%m-%d")
        seq = _next_seqnum(eval_runs_dir, today)
        run_id = EvalRunId(f"evalrun-{today}-{seq:03d}")
        path = eval_runs_dir / f"{run_id}.md"

        digest = "sha256:" + hashlib.sha256(repr(ctx.payload).encode()).hexdigest()[:16]

        run = cls(
            id=run_id,
            eval_ref=ref,
            eval_snapshot=eval_def.to_dict(),
            started_at=now(),
            status="running",
            context_digest=digest,
            _path=path,
        )
        run._save()
        return run

    @persists
    def finish(
        self,
        status: Literal["passed", "failed", "error"],
        score: float | None,
        output: str,
        cost_usd: float,
    ) -> None:
        if self.status != "running":
            raise InvalidTransition(
                entity_type="eval_run",
                entity_id=self.id,
                current_status=self.status,
                attempted_transition=f"finish({status})",
            )
        self.status = status
        self.score = score
        self.output = output[:8000]
        self.cost_usd = cost_usd
        self.completed_at = now()

    @classmethod
    def load(cls, path: Path) -> "EvalRun":
        from autopilot.domain.parse import parse_eval_run

        text = path.read_text(encoding="utf-8")
        run = parse_eval_run(text, path=path)
        run._path = path
        return run

    def _save(self) -> None:
        if self._path is None:
            raise ValidationError(
                entity_type="eval_run",
                entity_id=self.id,
                field="_path",
                reason="_path must be set before _save()",
            )
        fm: dict[str, Any] = {
            "id": self.id,
            "eval_ref": {
                "entity_type": self.eval_ref.entity_type,
                "entity_id": self.eval_ref.entity_id,
                "eval_index": self.eval_ref.eval_index,
            },
            "eval_snapshot": self.eval_snapshot,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at) if self.completed_at else None,
            "status": self.status,
            "score": self.score,
            "cost_usd": self.cost_usd,
            "context_digest": self.context_digest,
        }
        body = f"# EvalRun {self.id}\n\n```\n{self.output}\n```"
        content = f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}\n"
        atomic_write(self._path, content)


def _next_seqnum(dir_path: Path, date_str: str) -> int:
    prefix = f"evalrun-{date_str}-"
    existing: list[int] = []
    if dir_path.exists():
        for p in dir_path.glob(f"{prefix}*.md"):
            stem = p.stem  # evalrun-YYYY-MM-DD-nnn
            tail = stem[len(prefix) :]
            try:
                existing.append(int(tail))
            except ValueError:
                continue
    return (max(existing) + 1) if existing else 1


def _iso(dt: datetime) -> str:
    """ISO-8601 UTC with trailing Z."""
    s = dt.isoformat()
    if s.endswith("+00:00"):
        s = s[: -len("+00:00")] + "Z"
    return s


_SCORE_RE = re.compile(r"SCORE:\s*(\d+(?:\.\d+)?)")
_MAX_JUDGE_PARSE_RETRIES = 2


async def run_eval(eval_def: Eval, ref: EvalRef, ctx: EvalContext) -> EvalRun:
    """Execute an eval and return the EvalRun record.

    Expected `ctx.payload` keys:
      - `project_root: Path` — for eval-runs directory placement
      - `entity_dir: Path` — directory of the containing entity file (for
        resolving relative `script` / `prompt_file` paths)
      - `worker_model: str` — enforced != judge_model for judge evals
      - `cfg: AutopilotConfig` — passed through to `run_agent` for judge evals

    Per design §12.3: `domain/eval.py` is the execution primitive, so
    subprocess/asyncio live here deliberately. §12.12: sequential — no gather.
    """
    run = EvalRun.start(ref, eval_def, ctx)
    t0 = time.monotonic()
    try:
        match eval_def.type:
            case "shell":
                status, score, output, cost = await _run_shell(eval_def, ctx)
            case "judge":
                status, score, output, cost = await _run_judge(eval_def, ref, ctx)
            case "metric":
                raise NotImplementedError("metric eval execution deferred to Frink (design §5.5)")
            case _:
                raise ValidationError(
                    entity_type="eval",
                    entity_id=None,
                    field="type",
                    reason=f"unknown eval type: {eval_def.type}",
                )
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        run.finish(status="error", score=None, output=str(e), cost_usd=0.0)
        emit(
            "eval.run",
            **{
                "eval.type": eval_def.type,
                "eval.ref": f"{ref.entity_type}/{ref.entity_id}#{ref.eval_index}",
                "eval.status": "error",
            },
            duration_ms=duration_ms,
            cost_usd=0.0,
            **{"error.type": type(e).__name__, "error.message": str(e)},
        )
        raise

    duration_ms = int((time.monotonic() - t0) * 1000)
    run.finish(status=status, score=score, output=output, cost_usd=cost)
    emit(
        "eval.run",
        **{
            "eval.type": eval_def.type,
            "eval.ref": f"{ref.entity_type}/{ref.entity_id}#{ref.eval_index}",
            "eval.status": status,
        },
        duration_ms=duration_ms,
        cost_usd=cost,
    )
    return run


def _entity_dir(ctx: EvalContext) -> Path:
    d = ctx.payload.get("entity_dir")
    if not isinstance(d, Path):
        d = Path(d) if d else Path.cwd()
    return d


async def _run_shell(
    eval_def: Eval, ctx: EvalContext
) -> tuple[Literal["passed", "failed"], None, str, float]:
    """Shell runner: resolve command, run under timeout, exit 0 = passed."""
    if eval_def.script:
        script_path = (_entity_dir(ctx) / eval_def.script).resolve()
        if not script_path.exists():
            raise EvalFileNotFound(
                eval_ref="shell.script",
                missing_path=script_path,
            )
        cmd = str(script_path)
    elif eval_def.run:
        cmd = eval_def.run
    else:
        raise ValidationError(
            entity_type="eval",
            entity_id=None,
            field="run/script",
            reason="shell eval missing run/script at execution time",
        )

    # Shell evals run at the project root — that's where tests, linters, and
    # build tools expect to execute. `entity_dir` is used only for resolving
    # relative `script` paths (above).
    run_cwd = ctx.payload.get("project_root") or _entity_dir(ctx)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(run_cwd),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=eval_def.timeout_sec)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ("failed", None, f"eval timed out after {eval_def.timeout_sec}s", 0.0)

    output = (stdout or b"").decode("utf-8", errors="replace")
    status: Literal["passed", "failed"] = "passed" if proc.returncode == 0 else "failed"
    return (status, None, output, 0.0)


async def _run_judge(
    eval_def: Eval,
    ref: EvalRef,
    ctx: EvalContext,
) -> tuple[Literal["passed", "failed"], float, str, float]:
    """Judge runner: multi-round averaging of SCORE: <float> parsed from agent output.

    Pass rule (Phase 1): average >= 0.5. Threshold calibration is a Frink concern
    (design §5.5, principle 9).
    """
    worker_model = ctx.payload.get("worker_model")
    if worker_model and eval_def.judge_model == worker_model:
        raise JudgeModelCollision(
            judge_model=eval_def.judge_model,
            worker_model=str(worker_model),
        )

    cfg = ctx.payload.get("cfg")
    if cfg is None:
        raise ValidationError(
            entity_type="eval",
            entity_id=None,
            field="ctx.payload.cfg",
            reason="judge eval requires AutopilotConfig in ctx.payload['cfg']",
        )

    # Resolve prompt text.
    if eval_def.prompt_file:
        prompt_path = (_entity_dir(ctx) / eval_def.prompt_file).resolve()
        if not prompt_path.exists():
            raise EvalFileNotFound(
                eval_ref="judge.prompt_file",
                missing_path=prompt_path,
            )
        prompt_text = prompt_path.read_text(encoding="utf-8")
    elif eval_def.prompt:
        prompt_text = eval_def.prompt
    else:
        raise ValidationError(
            entity_type="eval",
            entity_id=None,
            field="prompt/prompt_file",
            reason="judge eval missing prompt/prompt_file at execution time",
        )

    # Lazy import — agents module owns the SDK dependency.
    from autopilot.agents.runner import run_agent

    scores: list[float] = []
    outputs: list[str] = []
    total_cost = 0.0

    rounds = max(1, eval_def.rounds)
    for round_n in range(rounds):
        # Judge parse-failure retry: only on *structural* failure (empty output or
        # agent call error). A SCORE-less but non-empty output falls through to the
        # neutral 0.5 default — "parseable but neutral," not a retry trigger (§2.3).
        attempt_output = ""
        attempt_cost = 0.0
        parse_ok = False
        last_err: str | None = None
        for attempt in range(_MAX_JUDGE_PARSE_RETRIES + 1):
            result = await run_agent("judge", prompt_text, cfg)
            attempt_cost = result.cost_usd
            total_cost += attempt_cost
            if not result.success or not (result.output or "").strip():
                last_err = result.error or "empty output"
                continue
            attempt_output = result.output
            parse_ok = True
            break

        if not parse_ok:
            outputs.append(
                f"[round {round_n + 1}] judge call failed: {last_err or 'unknown error'}"
            )
            # Treat as neutral for averaging; run status will depend on overall avg.
            scores.append(0.5)
            continue

        outputs.append(f"[round {round_n + 1}]\n{attempt_output}")
        m = _SCORE_RE.search(attempt_output)
        if m:
            try:
                scores.append(float(m.group(1)))
            except ValueError:
                scores.append(0.5)
        else:
            # Parseable but no SCORE line — neutral.
            scores.append(0.5)

    avg = sum(scores) / len(scores) if scores else 0.5
    status: Literal["passed", "failed"] = "passed" if avg >= 0.5 else "failed"
    combined = "\n\n".join(outputs)
    combined = f"avg_score={avg:.3f} scores={scores}\n\n{combined}"
    _ = ref  # ref currently unused in judge output; reserved for future context digest
    return (status, avg, combined, total_cost)
