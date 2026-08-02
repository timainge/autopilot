"""Frink: explorative experiment loop. Per .dev/phase-5-frink.md §7 (as amended).

Principle #F1: the harness scaffolds (branch lifecycle, budget, HIL gating,
persistence); Claude Code decides (what to try, what to keep, when to stop,
what was learned). Any signal-reading decision rule in Python here is a bug.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from autopilot.agents.prompts import (
    build_frink_reviewer_prompt,
    build_frink_runner_prompt,
    build_frink_stop_judge_prompt,
)
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.clock import now
from autopilot.domain.errors import JudgeModelCollision, ParseError
from autopilot.domain.experiment import Experiment, Lap
from autopilot.domain.parse import parse_runner_output, parse_stop_judge_verdict
from autopilot.domain.persists import atomic_write
from autopilot.log import emit
from autopilot.orchestrator import gitops


@dataclass
class FrinkOutcome:
    experiment: Experiment


def _next_experiment_id(root: Path) -> str:
    existing: list[int] = []
    if root.is_dir():
        for p in root.glob("exp-*"):
            if not p.is_dir():
                continue
            try:
                existing.append(int(p.name[len("exp-") :]))
            except ValueError:
                continue
    return f"exp-{(max(existing) + 1 if existing else 1):03d}"


def _next_lap_id(exp: Experiment) -> str:
    existing: list[int] = []
    if exp._dir is not None:
        for p in exp._dir.glob("lap-*.md"):
            stem = p.name.removesuffix(".pending.md").removesuffix(".md")
            try:
                existing.append(int(stem[len("lap-") :]))
            except ValueError:
                continue
    return f"lap-{(max(existing) + 1 if existing else 1):03d}"


def _seed_kb(project: Path, exp: Experiment) -> None:
    """Seed `kb/` per §10: bundled-runbook fallback (no archetype manifests yet)."""
    assert exp._dir is not None
    kb = exp._dir / "kb"
    for sub in ("runbooks", "research", "prior-reviews", "ad-hoc"):
        (kb / sub).mkdir(parents=True, exist_ok=True)

    archetype: str | None = None
    roadmap_path = project / ".dev" / "roadmap.md"
    if roadmap_path.is_file():
        from autopilot.domain.roadmap import Roadmap

        try:
            archetype = Roadmap.load(roadmap_path).archetype
        except Exception:  # noqa: BLE001 — seeding is best-effort; a bad roadmap isn't fatal
            archetype = None

    from autopilot import runbooks as runbooks_pkg

    runbooks_dir = Path(runbooks_pkg.__file__).parent
    candidate = runbooks_dir / f"{archetype}.md" if archetype else None
    if candidate is None or not candidate.is_file():
        fallback = runbooks_dir / "python-cli.md"
        if candidate is not None:
            emit(
                "frink.kb.seed",
                experiment=exp.id,
                warning=f"no bundled runbook for archetype {archetype!r}; using fallback",
            )
        candidate = fallback if fallback.is_file() else None
    if candidate is not None:
        link = kb / "runbooks" / candidate.name
        if not link.exists():
            link.symlink_to(candidate)


def _create_or_resume_experiment(
    project: Path,
    mode: Literal["build", "tune", "research"],
    objective: str,
    rubric: str,
    hil_required: bool,
    goal_id: str | None,
    head_branch: str,
) -> Experiment:
    root = project / ".dev" / "experiments"
    root.mkdir(parents=True, exist_ok=True)
    for d in sorted(root.glob("exp-*")):
        if not (d / f"{d.name}.md").is_file():
            continue
        exp = Experiment.load(d)
        if exp.status == "running" and exp.objective.strip() == objective.strip():
            emit("frink.resume", experiment=exp.id, laps=len(exp.laps))
            return exp
    exp = Experiment(
        id=_next_experiment_id(root),
        mode=mode,
        objective=objective,
        rubric=rubric,
        hil_required=hil_required,
        goal_id=goal_id,
        head_branch=head_branch,
    )
    exp._dir = root / exp.id
    exp._save()
    _seed_kb(project, exp)
    return exp


async def _hil_approve(
    lap: Lap, verdict: str, reason: str, cfg: AutopilotConfig
) -> tuple[str, str]:
    """Filesystem HIL gate per §7.2. Blocks on `lap-NNN.pending.md`.

    Human accepts by deleting the file, or edits `accepted: true|false` with
    optional `override_verdict:` / `override_reason:`. Timeout → discard.
    """
    assert lap._path is not None
    pending = lap._path.with_name(f"{lap.id}.pending.md")
    atomic_write(
        pending,
        yaml.safe_dump({"proposed_verdict": verdict, "proposed_reason": reason}, sort_keys=False),
    )
    waited = 0
    while waited < cfg.frink_hil_timeout_sec:
        await asyncio.sleep(cfg.frink_hil_poll_sec)
        waited += cfg.frink_hil_poll_sec
        if not pending.exists():
            return verdict, reason  # accepted as proposed
        try:
            data = yaml.safe_load(pending.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue  # human mid-edit; poll again
        if not isinstance(data, dict) or "accepted" not in data:
            continue
        pending.unlink(missing_ok=True)
        if data["accepted"]:
            override = str(data.get("override_verdict", verdict))
            if override not in ("merge", "discard", "iterate"):
                # Typo'd override must not crash the loop after branch ops:
                # keep the judge's proposal, note the rejected override.
                emit("frink.hil.invalid_override", lap=lap.id, override=override)
                return verdict, f"{reason} [invalid HIL override {override!r} ignored]"
            return override, str(data.get("override_reason", reason))
        return "discard", str(data.get("override_reason", "rejected by human"))
    pending.unlink(missing_ok=True)
    emit("frink.hil.timeout", lap=lap.id, timeout_sec=cfg.frink_hil_timeout_sec)
    return "discard", f"HIL timeout after {cfg.frink_hil_timeout_sec}s"


async def _apply_verdict(project: Path, exp: Experiment, lap: Lap, verdict: str) -> None:
    """Branch lifecycle per §7.1. Assumes the experiment head branch is checked out."""
    assert lap.branch is not None
    if verdict == "merge":
        await gitops.merge_no_ff(project, lap.branch, f"{exp.id}: merge {lap.id}")
        await gitops.delete_branch(project, lap.branch)
    elif verdict == "discard":
        await gitops.delete_branch(project, lap.branch)
    # iterate: keep the lap branch alive; the next lap bases off it.


async def _run_reviewer(exp: Experiment, cfg: AutopilotConfig, project: Path) -> None:
    """Always runs on terminal state. Reviewer failure is logged, never raised."""
    try:
        result = await run_agent(
            "frink-reviewer",
            build_frink_reviewer_prompt(exp),
            cfg,
            cwd=project,
            model=cfg.frink_reviewer_model,
        )
    except Exception as e:  # noqa: BLE001 — reviewer must not mask the loop outcome
        emit("frink.reviewer.error", experiment=exp.id, error=str(e))
        return
    if not result.success:
        emit("frink.reviewer.error", experiment=exp.id, error=result.error or "unknown")
        return
    assert exp._dir is not None
    atomic_write(exp._dir / "review.md", result.output)
    exp.add_cost(result.cost_usd)


async def frink(
    project: Path,
    cfg: AutopilotConfig,
    *,
    mode: Literal["build", "tune", "research"],
    objective: str,
    rubric: str,
    hil_required: bool = False,
    goal_id: str | None = None,
) -> FrinkOutcome:
    if cfg.frink_stop_judge_model == cfg.frink_runner_model:
        raise JudgeModelCollision(
            judge_model=cfg.frink_stop_judge_model, worker_model=cfg.frink_runner_model
        )
    if await gitops.tracked_under(project, ".dev"):
        from autopilot.domain.errors import CLIError

        raise CLIError(
            reason=".dev/ is git-tracked; frink's branch lifecycle requires it "
            "ignored (add `.dev/` to .gitignore and `git rm -r --cached .dev`)"
        )
    current = await gitops.current_branch(project)
    exp = _create_or_resume_experiment(
        project, mode, objective, rubric, hil_required, goal_id, head_branch=current
    )
    head = exp.head_branch or current
    if current != head:
        # Resuming after a kill mid-lap: park abandoned work, return to head.
        await gitops.commit_all_if_dirty(project, f"{exp.id}: abandoned lap work")
        await gitops.checkout(project, head)
    try:
        for _ in range(cfg.frink_max_iterations):
            if exp.cost_usd >= cfg.frink_max_cost_per_run_usd:
                exp.exhaust(f"budget: ${exp.cost_usd:.2f} >= ${cfg.frink_max_cost_per_run_usd:.2f}")
                break

            lap_id = _next_lap_id(exp)
            branch = f"exp/{exp.id}/lap/{lap_id}"
            base = (
                exp.laps[-1].branch
                if exp.laps and exp.laps[-1].verdict == "iterate" and exp.laps[-1].branch
                else head
            )
            if await gitops.branch_exists(project, branch):
                # Abandoned by a killed run (no lap file was written) — recreate.
                await gitops.delete_branch(project, branch)
            await gitops.create_and_checkout(project, branch, base)
            started = now()

            # 1. Agent plans + executes the lap.
            runner_result = await run_agent(
                "frink-runner",
                build_frink_runner_prompt(exp, lap_id),
                cfg,
                cwd=project,
                model=cfg.frink_runner_model,
            )
            lap_cost = runner_result.cost_usd
            await gitops.commit_all_if_dirty(project, f"{exp.id}/{lap_id}: lap work")
            if not runner_result.success:
                await gitops.checkout(project, head)
                await gitops.delete_branch(project, branch)
                exp.stop(f"runner failed on {lap_id}: {runner_result.error}")
                break

            # 2. Agent judges the outcome — still on the lap branch, so the
            #    judge's read-only spot-checks see the lap's state. Unparseable
            #    runner output → discard, matching planner parse-failure handling.
            signals: dict[str, Any]
            try:
                spec, signals = parse_runner_output(runner_result.output)
            except ParseError as e:
                spec, signals = "(unparseable runner output)", {}
                verdict, reason, done = "discard", f"runner output unparseable: {e}", False
            else:
                judge_result = await run_agent(
                    "frink-stop-judge",
                    build_frink_stop_judge_prompt(exp, spec, signals),
                    cfg,
                    cwd=project,
                    model=cfg.frink_stop_judge_model,
                )
                lap_cost += judge_result.cost_usd
                if not judge_result.success:
                    await gitops.checkout(project, head)
                    await gitops.delete_branch(project, branch)
                    exp.stop(f"stop-judge failed on {lap_id}: {judge_result.error}")
                    break
                try:
                    sv = parse_stop_judge_verdict(judge_result.output)
                    verdict, reason, done = sv.verdict, sv.reason, sv.done
                except ParseError as e:
                    verdict, reason, done = (
                        "discard",
                        f"stop-judge output unparseable: {e}",
                        False,
                    )
            await gitops.checkout(project, head)

            lap = Lap(id=lap_id, experiment_id=exp.id, spec=spec, branch=branch, started_at=started)
            assert exp._dir is not None
            lap._path = exp._dir / f"{lap_id}.md"
            lap._save()

            # 3. HIL gate (filesystem signal).
            if exp.hil_required:
                verdict, reason = await _hil_approve(lap, verdict, reason, cfg)

            # 4. Apply verdict (branch merge / discard / keep).
            await _apply_verdict(project, exp, lap, verdict)

            # 5. Persist.
            lap.record(signals=signals, verdict=verdict, reason=reason, cost_usd=lap_cost)
            exp.record_lap(lap)
            exp.add_cost(lap_cost)

            if verdict == "merge" and done:
                exp.complete(summary=reason)
                break

        if exp.status == "running":
            exp.exhaust(f"iteration cap ({cfg.frink_max_iterations})")
    finally:
        await _run_reviewer(exp, cfg, project)

    return FrinkOutcome(experiment=exp)
