"""Lisa: research outer-loop. Per .dev/phase-5-lisa.md §8."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from autopilot.agents.prompts import (
    build_decomposer_prompt,
    build_research_judge_prompt,
    build_researcher_prompt,
    build_summariser_prompt,
    build_synthesiser_prompt,
)
from autopilot.agents.runner import run_agent
from autopilot.config import AutopilotConfig
from autopilot.domain.errors import BudgetExceeded, CLIError, ParseError
from autopilot.domain.parse import (
    _parse_enquiry_output,
    _parse_enquiry_plan,
    parse_coverage_verdict,
)
from autopilot.domain.research import Enquiry, ResearchRun
from autopilot.log import emit


def _slugify(brief: str, *, max_chars: int = 40) -> str:
    text = brief.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("-")
    return text or "research"


def _research_budget_limit(cfg: AutopilotConfig) -> float:
    return min(cfg.max_cost_per_run_usd, cfg.max_cost_per_research_run_usd)


def _check_budget(run: ResearchRun, cfg: AutopilotConfig) -> None:
    limit = _research_budget_limit(cfg)
    if run.cost_usd > limit:
        raise BudgetExceeded(scope="per_run", limit_usd=limit, actual_usd=run.cost_usd)


def _consume_steer(run_dir: Path, iteration: int) -> str | None:
    """Read steer.md if present, archive it to steer-iter-NNN.md, return its body."""
    steer_path = run_dir / "steer.md"
    if not steer_path.is_file():
        return None
    body = steer_path.read_text(encoding="utf-8")
    archive = run_dir / f"steer-iter-{iteration:03d}.md"
    archive.write_text(body, encoding="utf-8")
    steer_path.unlink()
    return body


def _format_gaps(gaps: list[str]) -> str:
    if not gaps:
        return "(no gaps)\n"
    return "\n".join(f"- {g}" for g in gaps) + "\n"


async def _decompose(
    run: ResearchRun,
    prior_gaps: list[str],
    steer: str | None,
    cfg: AutopilotConfig,
    project: Path,
) -> str:
    result = await run_agent(
        "decomposer",
        build_decomposer_prompt(run, prior_gaps, steer),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"decomposer call failed: {result.error or 'unknown error'}")
    run.cost_usd += result.cost_usd
    return result.output


async def _synthesise(run: ResearchRun, cfg: AutopilotConfig, project: Path) -> str:
    result = await run_agent("synthesiser", build_synthesiser_prompt(run), cfg, cwd=project)
    if not result.success:
        raise CLIError(reason=f"synthesiser call failed: {result.error or 'unknown error'}")
    run.cost_usd += result.cost_usd
    return result.output


async def _summarise(
    run: ResearchRun, report_text: str, cfg: AutopilotConfig, project: Path
) -> str:
    result = await run_agent(
        "synthesiser",
        build_summariser_prompt(run, report_text),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"summariser call failed: {result.error or 'unknown error'}")
    run.cost_usd += result.cost_usd
    return result.output


async def _research_judge(run: ResearchRun, report_text: str, cfg: AutopilotConfig, project: Path):  # noqa: ANN201 — local CoverageVerdict
    result = await run_agent(
        "research-judge",
        build_research_judge_prompt(run, report_text),
        cfg,
        cwd=project,
    )
    if not result.success:
        raise CLIError(reason=f"research-judge call failed: {result.error or 'unknown error'}")
    run.cost_usd += result.cost_usd
    return parse_coverage_verdict(result.output)


async def _run_enquiries_parallel(
    enquiries: list[Enquiry],
    run: ResearchRun,
    cfg: AutopilotConfig,
    project: Path,
) -> None:
    sem = asyncio.Semaphore(cfg.max_parallel_research)

    async def _one(enq: Enquiry) -> None:
        async with sem:
            try:
                _check_budget(run, cfg)
            except BudgetExceeded as e:
                enq._path = run._dir / f"enquiry-{enq.id}.md"
                enq._save()
                enq.fail(f"budget: {e}")
                return
            enq._path = run._dir / f"enquiry-{enq.id}.md"
            enq._save()
            enq.start()
            try:
                result = await asyncio.wait_for(
                    run_agent(
                        "researcher",
                        build_researcher_prompt(run.brief, enq),
                        cfg,
                        cwd=project,
                    ),
                    timeout=cfg.enquiry_timeout_sec,
                )
            except TimeoutError:
                enq.fail(f"timeout > {cfg.enquiry_timeout_sec}s")
                return
            except BudgetExceeded as e:
                enq.fail(f"budget: {e}")
                return
            if not result.success:
                enq.fail(result.error or "researcher failed")
                return
            try:
                findings, sources = _parse_enquiry_output(result.output)
            except ParseError as e:
                enq.fail(f"parse: {e}")
                return
            enq.complete(findings, sources, result.cost_usd)
            run.cost_usd += result.cost_usd
            run._save()

    await asyncio.gather(*(_one(e) for e in enquiries))


async def lisa(
    project: Path,
    cfg: AutopilotConfig,
    brief: str,
    *,
    slug: str | None = None,
    max_iterations: int | None = None,
) -> ResearchRun:
    """Run one research investigation: plan → research × N → synthesise → judge → loop."""
    slug = slug or _slugify(brief)
    research_root = project / ".dev" / "research"
    run_dir = research_root / slug
    topic_file = research_root / f"{slug}.md"
    if run_dir.exists():
        raise CLIError(reason=f"research slug already exists: {run_dir}")
    if topic_file.exists():
        raise CLIError(reason=f"slug collides with analyst topic file: {topic_file}")

    run = ResearchRun(slug=slug, brief=brief)
    run._dir = run_dir
    run_dir.mkdir(parents=True)
    run._save()
    emit("lisa.start", slug=slug)

    iter_cap = max_iterations if max_iterations is not None else cfg.max_research_iterations
    prior_gaps: list[str] = []
    report_text = ""

    for _ in range(iter_cap):
        try:
            _check_budget(run, cfg)
        except BudgetExceeded as e:
            run.stop(f"budget: {e}")
            emit("lisa.end", slug=slug, status="stopped", reason="budget")
            return run

        steer = _consume_steer(run_dir, run.iteration + 1)

        try:
            plan_text = await _decompose(run, prior_gaps, steer, cfg, project)
        except BudgetExceeded as e:
            run.stop(f"budget: {e}")
            emit("lisa.end", slug=slug, status="stopped", reason="budget")
            return run
        (run_dir / "plan.md").write_text(plan_text, encoding="utf-8")

        try:
            enquiries = _parse_enquiry_plan(
                plan_text,
                starting_id=len(run.enquiries) + 1,
                iteration=run.iteration + 1,
                cap=cfg.max_enquiries_per_iteration,
            )
        except ParseError as e:
            run.stop(f"decomposer parse error: {e}")
            emit("lisa.end", slug=slug, status="stopped", reason="parse")
            return run

        run.start_iteration()
        emit("lisa.iteration", slug=slug, iteration=run.iteration, enquiries=len(enquiries))

        await _run_enquiries_parallel(enquiries, run, cfg, project)
        run.record_enquiries(enquiries)

        if all(e.status == "failed" for e in enquiries):
            run.stop(f"iteration {run.iteration}: all enquiries failed")
            emit("lisa.end", slug=slug, status="stopped", reason="all_enquiries_failed")
            return run

        run.mark_synthesising()
        try:
            report_text = await _synthesise(run, cfg, project)
        except BudgetExceeded as e:
            run.stop(f"budget: {e}")
            emit("lisa.end", slug=slug, status="stopped", reason="budget")
            return run
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")

        run.mark_evaluating()
        try:
            verdict = await _research_judge(run, report_text, cfg, project)
        except BudgetExceeded as e:
            run.stop(f"budget: {e}")
            emit("lisa.end", slug=slug, status="stopped", reason="budget")
            return run
        run.record_coverage(verdict.gaps)
        (run_dir / "gaps.md").write_text(_format_gaps(verdict.gaps), encoding="utf-8")

        if verdict.satisfied:
            try:
                summary = await _summarise(run, report_text, cfg, project)
            except BudgetExceeded as e:
                run.stop(f"budget: {e}")
                emit("lisa.end", slug=slug, status="stopped", reason="budget")
                return run
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")
            run.satisfy(summary)
            emit("lisa.end", slug=slug, status="satisfied")
            return run
        prior_gaps = verdict.gaps

    # Iteration cap exhausted.
    try:
        summary = await _summarise(run, report_text, cfg, project)
    except BudgetExceeded as e:
        run.stop(f"budget: {e}")
        emit("lisa.end", slug=slug, status="stopped", reason="budget")
        return run
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    run.cap(summary + "\n\n[capped at max_research_iterations]")
    emit("lisa.end", slug=slug, status="capped")
    return run
