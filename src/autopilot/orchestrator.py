"""Core orchestration loop — processes projects through judge/worker pipeline."""

import asyncio
from pathlib import Path

from .agent import run_agent
from .config import AutopilotConfig, load_config
from .log import log
from .manifest import (
    append_sprint_log,
    get_next_task,
    get_task_summary,
    load_agent_config,
    load_archetypes_index,
    load_roadmap_text,
    load_runbook,
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
    review: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the planner agent to create or improve a project manifest."""
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    # Without explicit context, lazily run research + roadmap if artifacts don't exist
    if not context_file:
        if not cfg.summary_path(project_path).exists():
            log(project_name, "No context provided — running research first", "🔬")
            await research_project(project_path, agents_dir, cfg=cfg)

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

    if not result.success or not review:
        return

    try:
        critic_config = load_agent_config("critic", agents_dir)
    except FileNotFoundError:
        log(project_name, "No critic agent config found — skipping review", "⚠️")
        return

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
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run the roadmap agent on a single project."""
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

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


async def process_project(
    project_path: Path,
    agents_dir: Path,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Process a single project through the orchestration pipeline."""
    project_name = project_path.name
    if cfg is None:
        cfg = load_config(project_path)

    manifest = load_sprint_plan(project_path, cfg)
    if manifest is None:
        manifest_hint = cfg.sprint_path(project_path)
        log(project_name, f"No {manifest_hint} found — skipping", "⏭️")
        return

    log(project_name, f"Loaded manifest: {manifest.name} ({get_task_summary(manifest)})", "📋")

    if manifest.status == "completed":
        log(project_name, "Project already completed", "✅")
        return

    if manifest.status == "paused":
        log(project_name, "Project is paused — skipping", "⏸️")
        return

    if manifest.status == "stuck":
        log(project_name, "Project is stuck — run 'autopilot run --resume' to retry", "🛑")
        return

    # --- Step 1: Check approval / run judge ---

    if not manifest.approved:
        log(project_name, "Not approved — running readiness evaluation...", "🔍")

        try:
            judge_config = load_agent_config("judge", agents_dir)
        except FileNotFoundError:
            log(project_name, "No judge agent config found — skipping", "❌")
            return

        judge_prompt = build_judge_prompt(manifest)
        result = await run_agent(
            judge_config,
            project_path,
            judge_prompt,
            project_name=project_name,
            role_name="judge",
        )

        if not result.success:
            log(project_name, f"Judge failed: {result.error}", "❌")
            return

        is_ready, feedback = parse_judge_result(result.output)

        if result.cost_usd > 0:
            log(project_name, f"Judge cost: ${result.cost_usd:.4f}", "💰")

        if not is_ready:
            log(project_name, "Judge verdict: NOT READY", "⚠️")
            for line in feedback.split("\n")[:15]:
                if line.strip():
                    print(f"           {line}")
            return

        log(project_name, "Judge verdict: READY", "✅")

        if auto_approve:
            update_manifest_frontmatter(manifest, {"approved": True})
            log(project_name, "Auto-approved — proceeding to task execution", "🚀")
            manifest = load_sprint_plan(project_path, cfg) or manifest
            # Fall through to task execution below
        else:
            log(project_name, "Set 'approved: true' in manifest to begin execution", "👉")
            return

    # --- Step 2: Execute tasks sequentially ---

    update_manifest_frontmatter(manifest, {"status": "active"})

    while True:
        task = get_next_task(manifest)

        if task is None:
            all_done = all(t.status == "done" for t in manifest.tasks)
            if all_done:
                update_manifest_frontmatter(manifest, {"status": "completed"})
                log(project_name, f"All tasks complete! ({get_task_summary(manifest)})", "🎉")
            else:
                stuck_tasks = [
                    t
                    for t in manifest.tasks
                    if t.status != "done" and t.attempts >= manifest.max_task_attempts
                ]
                blocked_tasks = [
                    t
                    for t in manifest.tasks
                    if t.status == "pending"
                    and not all(
                        dep in {tt.id for tt in manifest.tasks if tt.status == "done"}
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
                    summary = get_task_summary(manifest)
                    log(project_name, f"No runnable tasks remain ({summary})", "🛑")

                update_manifest_frontmatter(manifest, {"status": "stuck"})
            break

        task_idx = next((i for i, t in enumerate(manifest.tasks) if t.id == task.id), 0)
        total = len(manifest.tasks)
        attempt_str = f" (attempt {task.attempts + 1})" if task.attempts > 0 else ""

        log(
            project_name, f'Starting task {task_idx + 1}/{total}: "{task.title}"{attempt_str}', "🔧"
        )

        try:
            worker_config = load_agent_config("worker", agents_dir)
        except FileNotFoundError:
            log(project_name, "No worker agent config found — stopping", "❌")
            break

        worker_prompt = build_worker_prompt(manifest, task)
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
            updated_manifest = load_sprint_plan(project_path, cfg)
            if updated_manifest:
                updated_task = next((t for t in updated_manifest.tasks if t.id == task.id), None)
                if updated_task and updated_task.status == "done":
                    log(project_name, f'Task complete: "{task.title}"', "✅")
                    manifest = updated_manifest
                    continue
                else:
                    log(
                        project_name,
                        "Worker finished but task not marked done — treating as incomplete",
                        "⚠️",
                    )
                    update_task_status(
                        manifest,
                        task.id,
                        "pending",
                        error="Worker completed without marking task done",
                        attempts=new_attempts,
                    )
                    manifest = load_sprint_plan(project_path, cfg) or manifest
            else:
                log(project_name, "Could not reload manifest after task", "❌")
                break
        else:
            error_msg = result.error or "Unknown error"
            log(project_name, f"Task failed: {error_msg[:100]}", "❌")

            if new_attempts >= manifest.max_task_attempts:
                update_task_status(
                    manifest,
                    task.id,
                    "failed",
                    error=error_msg,
                    attempts=new_attempts,
                )
                max_att = manifest.max_task_attempts
                log(
                    project_name,
                    f'Task "{task.title}" exceeded {max_att} attempts — marking failed',
                    "🛑",
                )
            else:
                update_task_status(
                    manifest,
                    task.id,
                    "pending",
                    error=error_msg,
                    attempts=new_attempts,
                )
                log(project_name, f"Will retry ({new_attempts}/{manifest.max_task_attempts})", "🔄")

            manifest = load_sprint_plan(project_path, cfg) or manifest


async def sprint_project(
    project_path: Path,
    agents_dir: Path,
    auto_loop: bool = False,
    auto_approve: bool = False,
    cfg: AutopilotConfig | None = None,
) -> None:
    """Run one or more sprint cycles against the roadmap."""
    if cfg is None:
        cfg = load_config(project_path)

    project_name = project_path.name

    # Step 3: Load roadmap (replaces strategy manifest)
    roadmap_text = load_roadmap_text(project_path, cfg)
    if not roadmap_text:
        log(project_name, "No .dev/roadmap.md found — run 'autopilot roadmap .' first", "❌")
        return

    roadmap_fm, roadmap_body = parse_frontmatter(roadmap_text)
    roadmap_goal = roadmap_fm.get("goal", "")
    roadmap_archetype = roadmap_fm.get("archetype", "")

    if not roadmap_goal:
        log(project_name, "Roadmap has no goal — run 'autopilot roadmap .' to regenerate", "❌")
        return

    # Step 4: Load runbook based on archetype from roadmap
    runbook = load_runbook(roadmap_archetype, cfg) if roadmap_archetype else None
    sprint_log = load_sprint_log(project_path, cfg)
    archetypes_index = load_archetypes_index(cfg)

    # Step 5: Determine validation commands from roadmap frontmatter
    validation_commands: list[str] = roadmap_fm.get("validate") or []
    if not validation_commands and archetypes_index and roadmap_archetype:
        for entry in archetypes_index:
            if entry.get("name") == roadmap_archetype:
                validation_commands = entry.get("validate", [])
                break

    # Step 6: Determine sprint number
    sprint_number = sprint_log.count("## Sprint") + 1

    # --- Sprint loop ---
    while True:
        # Step 7: Check max_sprints
        if sprint_number > cfg.max_sprints:
            log(project_name, f"Reached max_sprints ({cfg.max_sprints}) — stopping", "🛑")
            break

        # Step 8: Run planner in sprint mode
        try:
            planner_config = load_agent_config("planner", agents_dir)
        except FileNotFoundError:
            log(project_name, "No planner agent config found — stopping", "❌")
            break

        log(project_name, f"Sprint {sprint_number}: Running planner...", "📝")
        planner_prompt = build_planner_prompt(
            project_path,
            sprint_mode=True,
            roadmap=roadmap_body,
            runbook=runbook or "",
            sprint_log=sprint_log,
        )
        planner_result = await run_agent(
            planner_config,
            project_path,
            planner_prompt,
            project_name=project_name,
            role_name="planner",
        )
        if not planner_result.success:
            log(project_name, f"Planner failed: {planner_result.error}", "❌")
            break

        # Step 9: Run critic (sprint_mode=True) — optional, skip if missing
        try:
            critic_config = load_agent_config("critic", agents_dir)
            log(project_name, "Running critic review...", "🔍")
            critic_prompt = build_critic_prompt(project_path, sprint_mode=True)
            await run_agent(
                critic_config,
                project_path,
                critic_prompt,
                project_name=project_name,
                role_name="critic",
            )
        except FileNotFoundError:
            log(project_name, "No critic agent config found — skipping", "⚠️")

        # Step 10: Load sprint plan
        sprint_manifest = load_sprint_plan(project_path, cfg)
        if sprint_manifest is None:
            log(project_name, "Planner did not write .dev/sprint.md — stopping", "❌")
            break

        # Step 11: Run judge on sprint plan
        try:
            judge_config = load_agent_config("judge", agents_dir)
        except FileNotFoundError:
            log(project_name, "No judge agent config found — stopping", "❌")
            break

        sprint_plan_path = str(cfg.sprint_path(project_path))
        judge_prompt = build_judge_prompt(sprint_manifest, sprint_plan_path=sprint_plan_path)
        judge_result = await run_agent(
            judge_config,
            project_path,
            judge_prompt,
            project_name=project_name,
            role_name="judge",
        )

        is_ready, _feedback = parse_judge_result(judge_result.output)

        if not is_ready and not auto_approve:
            log(
                project_name,
                "Sprint plan not approved — set approved: true in .dev/sprint.md to continue",
                "👉",
            )
            return
        elif not is_ready and auto_approve:
            log(project_name, "Sprint plan not ready but auto-approve is set — continuing", "⚠️")

        # Step 12: Execute tasks from sprint.md sequentially
        total_cost = 0.0
        tasks_completed = 0
        tasks_failed = 0

        async def _run_sprint_tasks() -> int:
            """Execute pending tasks from sprint plan. Returns tasks_planned count."""
            nonlocal total_cost, tasks_completed, tasks_failed
            while True:
                current_sprint = load_sprint_plan(project_path, cfg)
                if current_sprint is None:
                    break
                task = get_next_task(current_sprint)
                if task is None:
                    return len(current_sprint.tasks)
                try:
                    worker_config = load_agent_config("worker", agents_dir)
                except FileNotFoundError:
                    log(project_name, "No worker agent config found — stopping", "❌")
                    return len(current_sprint.tasks)

                task_idx = next(
                    (i for i, t in enumerate(current_sprint.tasks) if t.id == task.id), 0
                )
                total = len(current_sprint.tasks)
                attempt_str = f" (attempt {task.attempts + 1})" if task.attempts > 0 else ""
                log(
                    project_name,
                    f'Sprint task {task_idx + 1}/{total}: "{task.title}"{attempt_str}',
                    "🔧",
                )

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
                total_cost += result.cost_usd
                new_attempts = task.attempts + 1

                if result.success:
                    reloaded = load_sprint_plan(project_path, cfg)
                    if reloaded:
                        updated_task = next((t for t in reloaded.tasks if t.id == task.id), None)
                        if updated_task and updated_task.status == "done":
                            tasks_completed += 1
                            continue
                        else:
                            update_task_status(
                                current_sprint,
                                task.id,
                                "pending",
                                error="Worker completed without marking task done",
                                attempts=new_attempts,
                            )
                else:
                    if new_attempts >= current_sprint.max_task_attempts:
                        update_task_status(
                            current_sprint,
                            task.id,
                            "failed",
                            error=result.error or "Unknown error",
                            attempts=new_attempts,
                        )
                        tasks_failed += 1
                    else:
                        update_task_status(
                            current_sprint,
                            task.id,
                            "pending",
                            error=result.error or "Unknown error",
                            attempts=new_attempts,
                        )

            # fallback: reload to get final task count
            final = load_sprint_plan(project_path, cfg)
            return len(final.tasks) if final else 0

        tasks_planned = await _run_sprint_tasks()

        # Step 13: Run validation hooks
        validation_passed, validation_output = await run_validation_hooks(
            project_path, validation_commands
        )

        if not validation_passed:
            log(project_name, "Validation failed — attempting remediation", "⚠️")

        remediation_retries = 0
        while not validation_passed and remediation_retries < 2:
            remediation_retries += 1
            remediation_context = f"Validation failed:\n{validation_output}"
            combined_sprint_log = f"{sprint_log}\n\nREMEDIATION CONTEXT:\n{remediation_context}"

            log(
                project_name,
                f"Remediation attempt {remediation_retries}/2 — re-running planner...",
                "🔄",
            )
            try:
                rem_planner_config = load_agent_config("planner", agents_dir)
            except FileNotFoundError:
                log(project_name, "No planner agent config found — stopping remediation", "❌")
                break

            remediation_prompt = build_planner_prompt(
                project_path,
                sprint_mode=True,
                roadmap=roadmap_body,
                runbook=runbook or "",
                sprint_log=combined_sprint_log,
            )
            rem_result = await run_agent(
                rem_planner_config,
                project_path,
                remediation_prompt,
                project_name=project_name,
                role_name="planner",
            )
            if rem_result.success:
                tasks_planned = await _run_sprint_tasks()

            validation_passed, validation_output = await run_validation_hooks(
                project_path, validation_commands
            )

        if not validation_passed:
            log(project_name, "Validation still failing after remediation attempts", "❌")

        # Step 14: Evaluate
        goal_met, assessment = await evaluate_project(project_path, agents_dir, cfg=cfg)

        # Step 15: Build and append SprintResult
        sr = SprintResult(
            sprint_number=sprint_number,
            tasks_planned=tasks_planned,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            validation_passed=validation_passed,
            evaluation=assessment,
            strategy_satisfied=goal_met,
            cost_usd=total_cost,
        )
        append_sprint_log(project_path, sr, cfg)
        sprint_log = load_sprint_log(project_path, cfg)

        if total_cost > 0:
            log(project_name, f"Sprint {sprint_number} cost: ${total_cost:.4f}", "💰")

        # Step 16: Log outcome
        if goal_met:
            log(project_name, f"Sprint {sprint_number}: Goal met!", "🎉")
        else:
            log(project_name, f"Sprint {sprint_number}: Goal not yet met", "🔄")

        # Step 17: Break if satisfied or not looping
        if goal_met or not auto_loop:
            break

        # Step 18: Continue to next sprint
        sprint_number += 1
