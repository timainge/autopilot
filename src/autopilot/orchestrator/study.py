"""Study: matrix validation runner. Per .dev/phase-6-study.md.

Not a loop: the cell plan is fixed at spec time, cells run mechanically,
and the only agent calls are the treatment command itself (shell,
agent-agnostic) and the final analyst write-up. No judge, no iteration —
zero decisions in Python because a study has none to make.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path

from autopilot.agents.prompts import build_study_analyst_prompt
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.errors import CLIError
from autopilot.domain.parse import parse_study_spec
from autopilot.domain.persists import atomic_write
from autopilot.domain.study import Cell, Study
from autopilot.log import emit


@dataclass
class StudyOutcome:
    study: Study


def _next_study_id(root: Path) -> str:
    existing: list[int] = []
    if root.is_dir():
        for p in root.glob("study-*"):
            if not p.is_dir():
                continue
            try:
                existing.append(int(p.name[len("study-") :]))
            except ValueError:
                continue
    return f"study-{(max(existing) + 1 if existing else 1):03d}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def _derive_cells(study: Study) -> list[Cell]:
    """Cross-product over matrix keys (spec order) × repetitions. Deterministic order."""
    keys = list(study.matrix.keys())
    cells: list[Cell] = []
    for combo in itertools.product(*(study.matrix[k] for k in keys)):
        params = dict(zip(keys, combo, strict=True))
        for rep in range(1, study.repetitions + 1):
            cell_id = "-".join(_slug(v) for v in combo) + f"-r{rep}"
            cells.append(Cell(id=cell_id, study_id=study.id, params=params, rep=rep))
    return cells


def _substitute(template: str, params: dict[str, str]) -> str:
    out = template
    for k, v in params.items():
        out = out.replace("{" + k + "}", v)
    return out


def _same_spec(study: Study, spec: dict) -> bool:
    return (
        study.matrix == spec["matrix"]
        and study.run_cmd == spec["run"]
        and study.scorer_cmd == spec["scorer"]
        and study.repetitions == spec["repetitions"]
        and study.objective.strip() == spec["objective"].strip()
    )


def _create_or_resume_study(project: Path, spec: dict) -> Study:
    root = project / ".dev" / "studies"
    root.mkdir(parents=True, exist_ok=True)
    for d in sorted(root.glob("study-*")):
        if not (d / f"{d.name}.md").is_file():
            continue
        study = Study.load(d)
        # running = interrupted; stopped = had failed cells. Both resume with
        # an identical spec (completed cells kept). A completed study is
        # terminal — an identical re-run is deliberately a new study.
        if study.status in ("running", "stopped") and _same_spec(study, spec):
            if study.status == "stopped":
                study.resume()
            emit("study.resume", study=study.id, cells_on_disk=len(study.cells))
            return study
    study = Study(
        id=_next_study_id(root),
        objective=spec["objective"],
        matrix=spec["matrix"],
        run_cmd=spec["run"],
        scorer_cmd=spec["scorer"],
        repetitions=spec["repetitions"],
    )
    study._dir = root / study.id
    study._save()
    return study


async def _shell(cmd: str, cwd: Path, timeout_sec: int) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, f"timeout > {timeout_sec}s"
    return proc.returncode or 0, out_b.decode("utf-8", errors="replace")


async def _run_cell(cell: Cell, study: Study, cfg: AutopilotConfig, project: Path) -> None:
    assert study._dir is not None
    cell_dir = study._dir / "cells" / cell.id
    cell_dir.mkdir(parents=True, exist_ok=True)
    params = {
        **cell.params,
        "cell_dir": str(cell_dir),
        "project": str(project),
        "rep": str(cell.rep),
    }
    cell.start()

    rc, out = await _shell(_substitute(study.run_cmd, params), project, cfg.study_cell_timeout_sec)
    if rc != 0:
        cell.fail(f"treatment exit {rc}: {out.strip()[:500]}")
        return
    rc, out = await _shell(
        _substitute(study.scorer_cmd, params), project, cfg.study_cell_timeout_sec
    )
    if rc != 0:
        cell.fail(f"scorer exit {rc}: {out.strip()[:500]}")
        return

    scores_path = cell_dir / "scores.json"
    if not scores_path.is_file():
        cell.fail(f"scorer wrote no {scores_path.name}")
        return
    try:
        signals = json.loads(scores_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        cell.fail(f"invalid scores.json: {e}")
        return
    if not isinstance(signals, dict):
        cell.fail("scores.json must be a JSON object")
        return

    cost_raw = signals.get("cost_usd", 0.0)
    cost = float(cost_raw) if isinstance(cost_raw, int | float) else 0.0
    cell.complete(signals, cost)
    # A kill between these two writes loses this cell's cost from the study
    # total (completed cells never re-run). Accepted drift — same class as
    # Lisa's in-flight budget overshoot; per-cell cost stays on the cell.
    study.add_cost(cost)


async def run_analyst(study: Study, cfg: AutopilotConfig, project: Path) -> bool:
    """Analyst failure is logged, never raised — the cell data is the product.

    Returns True iff report.md was written. Refuses to analyse zero data.
    """
    if not any(c.status == "completed" for c in study.cells):
        emit("study.analyst.error", study=study.id, error="no completed cells to analyse")
        return False
    try:
        result = await run_agent(
            "study-analyst",
            build_study_analyst_prompt(study),
            cfg,
            cwd=project,
            model=cfg.study_analyst_model,
        )
    except Exception as e:  # noqa: BLE001 — analyst must not mask the run outcome
        emit("study.analyst.error", study=study.id, error=str(e))
        return False
    study.add_cost(result.cost_usd)  # a failed agent call still incurred cost
    if not result.success:
        emit("study.analyst.error", study=study.id, error=result.error or "unknown")
        return False
    assert study._dir is not None
    atomic_write(study._dir / "report.md", result.output)
    return True


async def study_run(project: Path, cfg: AutopilotConfig, spec_path: Path) -> StudyOutcome:
    if not spec_path.is_file():
        raise CLIError(reason=f"study spec not found: {spec_path}")
    spec = parse_study_spec(spec_path.read_text(encoding="utf-8"), path=spec_path)

    n_cells = 1
    for values in spec["matrix"].values():
        n_cells *= len(values)
    n_cells *= spec["repetitions"]
    if n_cells > cfg.study_max_cells:
        raise CLIError(
            reason=f"study would run {n_cells} cells > study_max_cells={cfg.study_max_cells}"
        )

    study = _create_or_resume_study(project, spec)
    assert study._dir is not None
    kept = {c.id: c for c in study.cells if c.status == "completed"}

    cells: list[Cell] = []
    for cell in _derive_cells(study):
        if cell.id in kept:
            cells.append(kept[cell.id])
            continue
        # Fresh, stale (killed mid-run), or failed cells run from scratch.
        cell._path = study._dir / f"cell-{cell.id}.md"
        cell._save()
        cells.append(cell)

    for cell in cells:
        if cell.status == "pending":
            await _run_cell(cell, study, cfg, project)

    # Cells own their files; the study file never persists them — this is a
    # view assignment (same as Study.load), not hidden state.
    study.cells = cells
    failed = [c for c in cells if c.status != "completed"]
    if cells and len(failed) == len(cells):
        study.stop("every cell failed")
        return StudyOutcome(study=study)

    reported = await run_analyst(study, cfg, project)
    tail = "see report.md" if reported else "analyst failed — no report"
    if failed:
        study.stop(f"{len(failed)}/{len(cells)} cells failed; {tail}")
    else:
        study.complete(f"all {len(cells)} cells completed; {tail}")
    return StudyOutcome(study=study)
