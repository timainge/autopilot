"""Core orchestration loop — processes projects through judge/worker pipeline."""

import asyncio
from pathlib import Path

from .agent import run_agent
from .config import AutopilotConfig, load_config
from .log import log
from .manifest import (
    append_deferred_to_roadmap,
    append_sprint_log,
    get_next_task,
    get_task_summary,
    load_agent_config,
    load_archetypes_index,
    load_roadmap_text,
    load_sprint_log,
    load_sprint_plan,
    parse_frontmatter,
    update_manifest_frontmatter,
    update_task_status,
)
from .models import SprintResult
from .prompts import (
    build_critic_prompt,
    build_deep_researcher_prompt,
    build_evaluate_prompt,
    build_judge_prompt,
    build_planner_prompt,
    build_portfolio_prompt,
    build_researcher_prompt,
    build_roadmap_prompt,
    build_worker_prompt,
    parse_goal_result,
    parse_judge_result,
)


async def plan_project(
    project_path: Path,
    agents_dir: Path,
    context_file: Path | None = None,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the planner agent to create or improve a project manifest.

    Runs: planner -> critic (if config exists) -> judge loop (up to 2 rounds).
    On judge READY, sets approved: true in sprint.md.
    """
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    # Without explicit context, lazily build roadmap if it doesn't exist
    if not context_file:
        if not cfg.roadmap_path(project_path).exists():
            log(project_name, "No roadmap found — building roadmap before planning", "🗺️")
            await roadmap_project(project_path, agents_dir, cfg=cfg)

    try:
        planner_config = load_agent_config("planner", agents_dir)
    except FileNotFoundError:
        log(project_name, "No planner agent config found — skipping", "❌")
        return

    ctx = f" (with context from {context_file.name})" if context_file else ""
    log(project_name, f"Running planner...{ctx}", "📝")

    prompt = build_planner_prompt(project_path, context_file)
    result = await run_agent(
        planner_config,
        project_path,
        prompt,
        project_name=project_name,
        role_name="planner",
    )

    if result.success:
        log(project_name, "Planning complete — see .dev/sprint.md", "✅")
    else:
        log(project_name, f"Planning failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Planner cost: ${result.cost_usd:.4f}", "💰")

    if not result.success:
        return

    # Critic always runs if config exists
    try:
        critic_config = load_agent_config("critic", agents_dir)
    except FileNotFoundError:
        log(project_name, "No critic agent config found — skipping", "⚠️")
    else:
        log(project_name, "Running critic review...", "🔍")
        critic_prompt = build_critic_prompt(project_path, context_file)
        critic_result = await run_agent(
            critic_config,
            project_path,
            critic_prompt,
            project_name=project_name,
            role_name="critic",
        )
        if critic_result.success:
            log(project_name, "Critic review complete", "✅")
        else:
            log(project_name, f"Critic review failed: {critic_result.error}", "❌")
        if critic_result.cost_usd > 0:
            log(project_name, f"Critic cost: ${critic_result.cost_usd:.4f}", "💰")

    # Judge loop: up to 2 rounds of plan -> judge -> (revise -> judge)
    max_judge_rounds = 2
    judge_feedback = ""

    for round_num in range(1, max_judge_rounds + 1):
        # If this is a revision round, re-run planner with feedback
        if round_num > 1 and judge_feedback:
            log(
                project_name,
                f"Judge round {round_num}/{max_judge_rounds}: revising plan...",
                "🔄",
            )
            revision_prompt = build_planner_prompt(
                project_path, context_file, judge_feedback=judge_feedback
            )
            rev_result = await run_agent(
                planner_config,
                project_path,
                revision_prompt,
                project_name=project_name,
                role_name="planner",
            )
            if not rev_result.success:
                log(project_name, f"Revision failed: {rev_result.error}", "❌")
                break
            if rev_result.cost_usd > 0:
                log(project_name, f"Revision cost: ${rev_result.cost_usd:.4f}", "💰")

            # Re-run critic on revised plan (optional)
            try:
                critic_config_r = load_agent_config("critic", agents_dir)
                critic_prompt_r = build_critic_prompt(project_path)
                await run_agent(
                    critic_config_r,
                    project_path,
                    critic_prompt_r,
                    project_name=project_name,
                    role_name="critic",
                )
            except FileNotFoundError:
                pass

        # Load current sprint plan for judge
        current_plan = load_sprint_plan(project_path, cfg)
        if current_plan is None:
            log(project_name, "No sprint.md found for judge — skipping", "⚠️")
            break

        try:
            judge_config = load_agent_config("judge", agents_dir)
        except FileNotFoundError:
            log(project_name, "No judge agent config found — skipping judge", "⚠️")
            break

        sprint_plan_path = str(cfg.sprint_path(project_path))
        log(
            project_name,
            f"Judge round {round_num}/{max_judge_rounds}: evaluating plan...",
            "🔍",
        )
        judge_prompt = build_judge_prompt(current_plan, sprint_plan_path=sprint_plan_path)
        judge_result = await run_agent(
            judge_config,
            project_path,
            judge_prompt,
            project_name=project_name,
            role_name="judge",
        )

        if judge_result.cost_usd > 0:
            log(project_name, f"Judge cost: ${judge_result.cost_usd:.4f}", "💰")

        is_ready, feedback = parse_judge_result(judge_result.output)

        if is_ready:
            update_manifest_frontmatter(current_plan, {"approved": True})
            log(project_name, "Judge verdict: READY — sprint.md approved", "✅")
            break
        else:
            log(
                project_name,
                f"Judge verdict: NOT_READY (round {round_num}/{max_judge_rounds})",
                "⚠️",
            )
            for line in feedback.split("\n")[:10]:
                if line.strip():
                    print(f"           {line}")
            judge_feedback = feedback
            if round_num == max_judge_rounds:
                log(
                    project_name,
                    "Could not approve plan after max revision rounds — review manually",
                    "❌",
                )
                log(
                    project_name,
                    "Set 'approved: true' in .dev/sprint.md when ready",
                    "👉",
                )


async def build_portfolio(
    scan_dir: Path,
    project_paths: list[Path],
    agents_dir: Path,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the portfolio agent to create a cross-project overview."""
    if cfg is None:
        cfg = load_config(scan_dir)

    try:
        portfolio_config = load_agent_config("portfolio", agents_dir)
    except FileNotFoundError:
        log("portfolio", "No portfolio agent config found", "❌")
        return

    with_summary = sum(1 for p in project_paths if cfg.summary_path(p).exists())
    log(
        "portfolio",
        f"Analyzing {len(project_paths)} projects ({with_summary} with research summaries)...",
        "📊",
    )

    prompt = build_portfolio_prompt(scan_dir, project_paths)
    result = await run_agent(
        portfolio_config,
        scan_dir,
        prompt,
        project_name="portfolio",
        role_name="portfolio",
    )

    portfolio_out = cfg.portfolio_path(scan_dir)
    if result.success:
        log("portfolio", f"Portfolio complete — see {portfolio_out}", "✅")
    else:
        log("portfolio", f"Portfolio failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log("portfolio", f"Portfolio cost: ${result.cost_usd:.4f}", "💰")


async def research_project(
    project_path: Path,
    agents_dir: Path,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the researcher agent on a single project."""
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    try:
        researcher_config = load_agent_config("researcher", agents_dir)
    except FileNotFoundError:
        log(project_name, "No researcher agent config found — skipping", "❌")
        return

    log(project_name, "Running project research...", "🔬")

    prompt = build_researcher_prompt(project_path)
    result = await run_agent(
        researcher_config,
        project_path,
        prompt,
        project_name=project_name,
        role_name="researcher",
    )

    summary_out = cfg.summary_path(project_path)
    if result.success:
        log(project_name, f"Research complete — see {summary_out}", "✅")
    else:
        log(project_name, f"Research failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Research cost: ${result.cost_usd:.4f}", "💰")


async def roadmap_project(
    project_path: Path,
    agents_dir: Path,
    deep: bool = False,
    topic: str | None = None,
    topic_file: Path | None = None,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the roadmap agent on a single project."""
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    # Topic mode: delegate entirely to deep researcher, no roadmap written
    if topic or topic_file:
        await deep_research_project(
            project_path, agents_dir, topic=topic, topic_file=topic_file, cfg=cfg
        )
        return

    # Deep mode: run deep researcher first to produce research reports, then proceed
    if deep:
        await deep_research_project(project_path, agents_dir, cfg=cfg)

    try:
        roadmap_config = load_agent_config("roadmap", agents_dir)
    except FileNotFoundError:
        log(project_name, "No roadmap agent config found — skipping", "❌")
        return

    has_summary = cfg.summary_path(project_path).exists()
    hint = " (from research summary)" if has_summary else " (no research summary — will assess)"
    log(project_name, f"Building shipping roadmap...{hint}", "🗺️")

    prompt = build_roadmap_prompt(project_path)
    result = await run_agent(
        roadmap_config,
        project_path,
        prompt,
        project_name=project_name,
        role_name="roadmap",
    )

    roadmap_out = cfg.roadmap_path(project_path)
    if result.success:
        log(project_name, f"Roadmap complete — see {roadmap_out}", "✅")
    else:
        log(project_name, f"Roadmap failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Roadmap cost: ${result.cost_usd:.4f}", "💰")


async def evaluate_project(
    project_path: Path,
    agents_dir: Path,
    cfg: AutopilotConfig | None = None,
) -> tuple[bool, str]:
    """Run the roadmap agent in evaluate mode. Returns (goal_met, assessment)."""
    if cfg is None:
        cfg = load_config(project_path)
    project_name = project_path.name
    try:
        roadmap_config = load_agent_config("roadmap", agents_dir)
    except FileNotFoundError:
        log(project_name, "No roadmap agent config found — skipping evaluation", "❌")
        return False, "Evaluation skipped (no roadmap agent config)"

    sprint_log = load_sprint_log(project_path, cfg)
    prompt = build_evaluate_prompt(project_path, sprint_log)
    result = await run_agent(
        roadmap_config,
        project_path,
        prompt,
        project_name=project_name,
        role_name="roadmap-evaluate",
    )
    if not result.success:
        log(project_name, f"Evaluation failed: {result.error}", "❌")
        return False, result.error or "Evaluation failed"
    if result.cost_usd > 0:
        log(project_name, f"Evaluation cost: ${result.cost_usd:.4f}", "💰")
    return parse_goal_result(result.output)


async def deep_research_project(
    project_path: Path,
    agents_dir: Path,
    topic: str | None = None,
    topic_file: Path | None = None,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the deep-researcher agent for thorough project or topic research."""
    if cfg is None:
        cfg = load_config(project_path)

    project_name = project_path.name

    try:
        researcher_config = load_agent_config("deep-researcher", agents_dir)
    except FileNotFoundError:
        log(project_name, "No deep-researcher agent config found — skipping", "❌")
        return

    topic_hint = ""
    if topic:
        topic_hint = f" (topic: {topic[:50]}...)"
    elif topic_file:
        topic_hint = f" (topic: {topic_file.name})"
    log(project_name, f"Running deep research...{topic_hint}", "🔬")

    prompt = build_deep_researcher_prompt(project_path, topic, topic_file)
    result = await run_agent(
        researcher_config,
        project_path,
        prompt,
        project_name=project_name,
        role_name="deep-researcher",
    )

    if result.success:
        log(project_name, "Deep research complete — see .dev/research/*/report.md", "✅")
    else:
        log(project_name, f"Deep research failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Deep research cost: ${result.cost_usd:.4f}", "💰")


async def run_validation_hooks(
    project_path: Path,
    commands: list[str],
    timeout: int = 120,
) -> tuple[bool, str]:
    """Run validation commands sequentially in the project directory.

    Returns (all_passed, combined_output). Stops on first failure.
    """
    if not commands:
        return (True, "")

    output = ""
    for cmd in commands:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            output += f"\n[Command timed out after {timeout}s: {cmd}]"
            return (False, output)

        output += stdout_bytes.decode("utf-8", errors="replace")
        output += stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            output += f"\n[Command failed with exit code {proc.returncode}: {cmd}]"
            return (False, output)

    return (True, output)


async def execute_sprint(
    project_path: Path,
    agents_dir: Path,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> tuple[int, int, int]:
    """Execute pending tasks from sprint.md.

    Returns (tasks_planned, tasks_completed, tasks_failed).
    """
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    sprint_manifest = load_sprint_plan(project_path, cfg)
    if sprint_manifest is None:
        log(project_name, "No .dev/sprint.md found — run 'autopilot plan .' first", "❌")
        return (0, 0, 0)

    log(
        project_name,
        f"Loaded sprint plan: {sprint_manifest.name} ({get_task_summary(sprint_manifest)})",
        "📋",
    )

    if sprint_manifest.status == "completed":
        log(project_name, "Sprint already completed", "✅")
        return (0, 0, 0)

    if sprint_manifest.status == "paused":
        log(project_name, "Sprint is paused — skipping", "⏸️")
        return (0, 0, 0)

    if sprint_manifest.status == "stuck":
        log(project_name, "Sprint is stuck — run 'autopilot sprint --resume .' to retry", "🛑")
        return (0, 0, 0)

    # Check approval
    if not sprint_manifest.approved:
        if not auto_approve:
            log(
                project_name,
                "sprint.md is not approved — run 'autopilot plan .' first,"
                " or set approved: true manually",
                "❌",
            )
            return (0, 0, 0)
        # auto_approve bypasses the check
        log(project_name, "Auto-approve: bypassing approval check", "⚠️")

    update_manifest_frontmatter(sprint_manifest, {"status": "active"})

    tasks_completed = 0
    tasks_failed = 0

    while True:
        current_sprint = load_sprint_plan(project_path, cfg)
        if current_sprint is None:
            break
        task = get_next_task(current_sprint)

        if task is None:
            all_done = all(t.status == "done" for t in current_sprint.tasks)
            if all_done:
                update_manifest_frontmatter(current_sprint, {"status": "completed"})
                log(
                    project_name,
                    f"All tasks complete! ({get_task_summary(current_sprint)})",
                    "🎉",
                )
            else:
                stuck_tasks = [
                    t
                    for t in current_sprint.tasks
                    if t.status != "done" and t.attempts >= current_sprint.max_task_attempts
                ]
                blocked_tasks = [
                    t
                    for t in current_sprint.tasks
                    if t.status == "pending"
                    and not all(
                        dep in {tt.id for tt in current_sprint.tasks if tt.status == "done"}
                        for dep in t.depends
                    )
                ]
                if stuck_tasks:
                    n = len(stuck_tasks)
                    log(project_name, f"Stuck — {n} task(s) exceeded max attempts", "🛑")
                    for t in stuck_tasks:
                        log(project_name, f"  → {t.title} ({t.attempts} attempts)", "")
                elif blocked_tasks:
                    n = len(blocked_tasks)
                    log(project_name, f"Blocked — {n} task(s) have unsatisfied deps", "🛑")
                else:
                    summary = get_task_summary(current_sprint)
                    log(project_name, f"No runnable tasks remain ({summary})", "🛑")
                update_manifest_frontmatter(current_sprint, {"status": "stuck"})
            break

        task_idx = next((i for i, t in enumerate(current_sprint.tasks) if t.id == task.id), 0)
        total = len(current_sprint.tasks)
        attempt_str = f" (attempt {task.attempts + 1})" if task.attempts > 0 else ""
        log(
            project_name,
            f'Starting task {task_idx + 1}/{total}: "{task.title}"{attempt_str}',
            "🔧",
        )

        try:
            worker_config = load_agent_config("worker", agents_dir)
        except FileNotFoundError:
            log(project_name, "No worker agent config found — stopping", "❌")
            break

        sprint_plan_path = str(cfg.sprint_path(project_path))
        worker_prompt = build_worker_prompt(
            current_sprint, task, sprint_plan_path=sprint_plan_path
        )
        result = await run_agent(
            worker_config,
            project_path,
            worker_prompt,
            project_name=project_name,
            role_name="worker",
        )

        if result.cost_usd > 0:
            log(project_name, f"Task cost: ${result.cost_usd:.4f}", "💰")

        new_attempts = task.attempts + 1

        if result.success:
            reloaded = load_sprint_plan(project_path, cfg)
            if reloaded:
                updated_task = next((t for t in reloaded.tasks if t.id == task.id), None)
                if updated_task and updated_task.status == "done":
                    tasks_completed += 1
                    log(project_name, f'Task complete: "{task.title}"', "✅")
                    continue
                else:
                    log(
                        project_name,
                        "Worker finished but task not marked done — treating as incomplete",
                        "⚠️",
                    )
                    update_task_status(
                        current_sprint,
                        task.id,
                        "pending",
                        error="Worker completed without marking task done",
                        attempts=new_attempts,
                    )
            else:
                log(project_name, "Could not reload sprint plan after task", "❌")
                break
        else:
            error_msg = result.error or "Unknown error"
            log(project_name, f"Task failed: {error_msg[:100]}", "❌")
            if new_attempts >= current_sprint.max_task_attempts:
                update_task_status(
                    current_sprint, task.id, "failed", error=error_msg, attempts=new_attempts
                )
                tasks_failed += 1
                max_att = current_sprint.max_task_attempts
                log(
                    project_name,
                    f'Task "{task.title}" exceeded {max_att} attempts — marking failed',
                    "🛑",
                )
            else:
                update_task_status(
                    current_sprint, task.id, "pending", error=error_msg, attempts=new_attempts
                )
                log(
                    project_name,
                    f"Will retry ({new_attempts}/{current_sprint.max_task_attempts})",
                    "🔄",
                )

    final = load_sprint_plan(project_path, cfg)
    tasks_planned = len(final.tasks) if final else 0
    return (tasks_planned, tasks_completed, tasks_failed)


async def build_project(
    project_path: Path,
    agents_dir: Path,
    context_file: Path | None = None,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run plan then execute sprint. One-shot: plan -> sprint."""
    if cfg is None:
        cfg = load_config(project_path)
    await plan_project(project_path, agents_dir, context_file=context_file, cfg=cfg)
    await execute_sprint(project_path, agents_dir, auto_approve=auto_approve, cfg=cfg)


async def ralph_project(
    project_path: Path,
    agents_dir: Path,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Outer loop: plan -> sprint -> evaluate until GOAL_MET or stuck."""
    if cfg is None:
        cfg = load_config(project_path)

    project_name = project_path.name

    # Require roadmap.md
    if not cfg.roadmap_path(project_path).exists():
        log(project_name, "No .dev/roadmap.md found — run 'autopilot roadmap .' first", "❌")
        return

    # Load validation commands from roadmap.md frontmatter
    roadmap_text = load_roadmap_text(project_path, cfg)
    roadmap_fm, _ = parse_frontmatter(roadmap_text)
    validation_commands: list[str] = roadmap_fm.get("validate") or []

    # Check archetypes index for default validate commands
    archetypes_index = load_archetypes_index(cfg)
    archetype = roadmap_fm.get("archetype", "")
    if not validation_commands and archetypes_index and archetype:
        for entry in archetypes_index:
            if entry.get("name") == archetype:
                validation_commands = entry.get("validate", [])
                break

    sprint_log = load_sprint_log(project_path, cfg)
    sprint_number = sprint_log.count("## Sprint") + 1

    while True:
        # Check max_sprints
        if sprint_number > cfg.max_sprints:
            log(project_name, f"Reached max_sprints ({cfg.max_sprints}) — stopping", "🛑")
            break

        log(project_name, f"=== Ralph Sprint {sprint_number} ===", "🔄")

        # Plan (internal: planner -> critic -> judge -> approved sprint.md)
        log(project_name, f"Sprint {sprint_number}: Planning...", "📝")
        await plan_project(project_path, agents_dir, cfg=cfg)

        # Check that plan succeeded and is approved
        sprint_manifest = load_sprint_plan(project_path, cfg)
        if sprint_manifest is None or not sprint_manifest.approved:
            log(project_name, "Plan not approved after planning — stopping ralph", "❌")
            log(
                project_name,
                "Review .dev/sprint.md and set approved: true, or fix the issues",
                "👉",
            )
            break

        # Execute sprint
        log(project_name, f"Sprint {sprint_number}: Executing...", "🔧")
        tasks_planned, tasks_completed, tasks_failed = await execute_sprint(
            project_path, agents_dir, cfg=cfg
        )

        # Stuck detection: if tasks failed, plant deferred task in roadmap.md
        if tasks_failed > 0:
            log(
                project_name,
                f"Sprint {sprint_number}: {tasks_failed} task(s) failed — stopping",
                "🛑",
            )
            log(project_name, "Appending deferred investigation task to roadmap.md", "📝")
            append_deferred_to_roadmap(project_path, cfg, sprint_number, tasks_failed)
            # Still evaluate and log before breaking
            goal_met, assessment = await evaluate_project(project_path, agents_dir, cfg=cfg)
            sr = SprintResult(
                sprint_number=sprint_number,
                tasks_planned=tasks_planned,
                tasks_completed=tasks_completed,
                tasks_failed=tasks_failed,
                validation_passed=False,
                evaluation=assessment,
                goal_met=goal_met,
                cost_usd=0.0,
            )
            append_sprint_log(project_path, sr, cfg)
            break

        # Validate
        validation_passed, validation_output = await run_validation_hooks(
            project_path, validation_commands
        )
        if not validation_passed:
            log(project_name, f"Sprint {sprint_number}: Validation failed", "⚠️")
            log(project_name, validation_output[:200], "")

        # Evaluate
        goal_met, assessment = await evaluate_project(project_path, agents_dir, cfg=cfg)

        # Append sprint log
        sr = SprintResult(
            sprint_number=sprint_number,
            tasks_planned=tasks_planned,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            validation_passed=validation_passed,
            evaluation=assessment,
            goal_met=goal_met,
            cost_usd=0.0,
        )
        append_sprint_log(project_path, sr, cfg)
        sprint_log = load_sprint_log(project_path, cfg)

        if goal_met:
            log(project_name, f"Sprint {sprint_number}: GOAL MET 🎉", "✅")
            break

        log(project_name, f"Sprint {sprint_number}: Goal not yet met — continuing", "🔄")
        sprint_number += 1
