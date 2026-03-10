"""Core orchestration loop — processes projects through judge/worker pipeline."""

from pathlib import Path

from .agent import run_agent
from .log import log
from .manifest import (
    get_next_task,
    get_task_summary,
    load_agent_config,
    load_manifest,
    update_manifest_frontmatter,
    update_task_status,
)
from .prompts import (
    build_critic_prompt,
    build_judge_prompt,
    build_planner_prompt,
    build_portfolio_prompt,
    build_roadmap_prompt,
    build_researcher_prompt,
    build_worker_prompt,
    parse_judge_result,
)


async def plan_project(
    project_path: Path,
    agents_dir: Path,
    context_file: Path | None = None,
    review: bool = False,
) -> None:
    """Run the planner agent to create or improve a project manifest."""
    project_name = project_path.name

    try:
        planner_config = load_agent_config("planner", agents_dir)
    except FileNotFoundError:
        log(project_name, "No planner agent config found — skipping", "❌")
        return

    ctx = f" (with context from {context_file.name})" if context_file else ""
    log(project_name, f"Running planner...{ctx}", "📝")

    prompt = build_planner_prompt(project_path, context_file)
    result = await run_agent(planner_config, project_path, prompt, project_name=project_name)

    if result.success:
        log(project_name, "Planning complete — see .dev/autopilot.md", "✅")
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
        critic_config, project_path, critic_prompt, project_name=project_name,
    )

    if critic_result.success:
        log(project_name, "Critic review complete", "✅")
    else:
        log(project_name, f"Critic review failed: {critic_result.error}", "❌")

    if critic_result.cost_usd > 0:
        log(project_name, f"Critic cost: ${critic_result.cost_usd:.4f}", "💰")


async def build_portfolio(
    scan_dir: Path, project_paths: list[Path], agents_dir: Path,
) -> None:
    """Run the portfolio agent to create a cross-project overview."""
    try:
        portfolio_config = load_agent_config("portfolio", agents_dir)
    except FileNotFoundError:
        log("portfolio", "No portfolio agent config found", "❌")
        return

    with_summary = sum(
        1 for p in project_paths
        if (p / ".dev" / "project-summary.md").exists()
    )
    log(
        "portfolio",
        f"Analyzing {len(project_paths)} projects "
        f"({with_summary} with research summaries)...",
        "📊",
    )

    prompt = build_portfolio_prompt(scan_dir, project_paths)
    result = await run_agent(portfolio_config, scan_dir, prompt, project_name="portfolio")

    if result.success:
        log("portfolio", f"Portfolio complete — see {scan_dir}/.dev/portfolio.md", "✅")
    else:
        log("portfolio", f"Portfolio failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log("portfolio", f"Portfolio cost: ${result.cost_usd:.4f}", "💰")


async def research_project(project_path: Path, agents_dir: Path) -> None:
    """Run the researcher agent on a single project."""
    project_name = project_path.name

    try:
        researcher_config = load_agent_config("researcher", agents_dir)
    except FileNotFoundError:
        log(project_name, "No researcher agent config found — skipping", "❌")
        return

    log(project_name, "Running project research...", "🔬")

    prompt = build_researcher_prompt(project_path)
    result = await run_agent(researcher_config, project_path, prompt, project_name=project_name)

    if result.success:
        log(project_name, "Research complete — see .dev/project-summary.md", "✅")
    else:
        log(project_name, f"Research failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Research cost: ${result.cost_usd:.4f}", "💰")


async def roadmap_project(project_path: Path, agents_dir: Path) -> None:
    """Run the roadmap agent on a single project."""
    project_name = project_path.name

    try:
        roadmap_config = load_agent_config("roadmap", agents_dir)
    except FileNotFoundError:
        log(project_name, "No roadmap agent config found — skipping", "❌")
        return

    has_summary = (project_path / ".dev" / "project-summary.md").exists()
    hint = " (from research summary)" if has_summary else " (no research summary — will assess)"
    log(project_name, f"Building shipping roadmap...{hint}", "🗺️")

    prompt = build_roadmap_prompt(project_path)
    result = await run_agent(roadmap_config, project_path, prompt, project_name=project_name)

    if result.success:
        log(project_name, "Roadmap complete — see .dev/roadmap.md", "✅")
    else:
        log(project_name, f"Roadmap failed: {result.error}", "❌")

    if result.cost_usd > 0:
        log(project_name, f"Roadmap cost: ${result.cost_usd:.4f}", "💰")


async def process_project(project_path: Path, agents_dir: Path) -> None:
    """Process a single project through the orchestration pipeline."""
    project_name = project_path.name

    manifest = load_manifest(project_path)
    if manifest is None:
        log(project_name, "No .dev/autopilot.md found — skipping", "⏭️")
        return

    log(project_name, f"Loaded manifest: {manifest.name} ({get_task_summary(manifest)})", "📋")

    if manifest.status == "completed":
        log(project_name, "Project already completed", "✅")
        return

    if manifest.status == "paused":
        log(project_name, "Project is paused — skipping", "⏸️")
        return

    if manifest.status == "stuck":
        log(project_name, "Project is stuck — run 'autopilot --resume' to retry failed tasks", "🛑")
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
            judge_config, project_path, judge_prompt, project_name=project_name,
        )

        if not result.success:
            log(project_name, f"Judge failed: {result.error}", "❌")
            return

        is_ready, feedback = parse_judge_result(result.output)

        if is_ready:
            log(project_name, "Judge verdict: READY", "✅")
            log(project_name, "Set 'approved: true' in manifest to begin execution", "👉")
        else:
            log(project_name, "Judge verdict: NOT READY", "⚠️")

        for line in feedback.split("\n")[:15]:
            if line.strip():
                print(f"           {line}")

        if result.cost_usd > 0:
            log(project_name, f"Judge cost: ${result.cost_usd:.4f}", "💰")

        return  # Never auto-approve

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
                    t for t in manifest.tasks
                    if t.status != "done" and t.attempts >= manifest.max_task_attempts
                ]
                blocked_tasks = [
                    t for t in manifest.tasks
                    if t.status == "pending" and not all(
                        dep in {tt.id for tt in manifest.tasks if tt.status == "done"}
                        for dep in t.depends
                    )
                ]
                if stuck_tasks:
                    log(project_name, f"Stuck — {len(stuck_tasks)} task(s) exceeded max attempts", "🛑")
                    for t in stuck_tasks:
                        log(project_name, f"  → {t.title} ({t.attempts} attempts)", "")
                elif blocked_tasks:
                    log(project_name, f"Blocked — {len(blocked_tasks)} task(s) have unsatisfied deps", "🛑")
                else:
                    log(project_name, f"No runnable tasks remain ({get_task_summary(manifest)})", "🛑")

                update_manifest_frontmatter(manifest, {"status": "stuck"})
            break

        task_idx = next(
            (i for i, t in enumerate(manifest.tasks) if t.id == task.id), 0
        )
        total = len(manifest.tasks)
        attempt_str = f" (attempt {task.attempts + 1})" if task.attempts > 0 else ""

        log(project_name,
            f"Starting task {task_idx + 1}/{total}: \"{task.title}\"{attempt_str}",
            "🔧")

        try:
            worker_config = load_agent_config("worker", agents_dir)
        except FileNotFoundError:
            log(project_name, "No worker agent config found — stopping", "❌")
            break

        worker_prompt = build_worker_prompt(manifest, task)
        result = await run_agent(
            worker_config, project_path, worker_prompt, project_name=project_name,
        )

        if result.cost_usd > 0:
            log(project_name, f"Task cost: ${result.cost_usd:.4f}", "💰")

        new_attempts = task.attempts + 1

        if result.success:
            updated_manifest = load_manifest(project_path)
            if updated_manifest:
                updated_task = next(
                    (t for t in updated_manifest.tasks if t.id == task.id), None
                )
                if updated_task and updated_task.status == "done":
                    log(project_name, f"Task complete: \"{task.title}\"", "✅")
                    manifest = updated_manifest
                    continue
                else:
                    log(project_name,
                        "Worker finished but task not marked done — treating as incomplete",
                        "⚠️")
                    update_task_status(
                        manifest, task.id, "pending",
                        error="Worker completed without marking task done",
                        attempts=new_attempts,
                    )
                    manifest = load_manifest(project_path) or manifest
            else:
                log(project_name, "Could not reload manifest after task", "❌")
                break
        else:
            error_msg = result.error or "Unknown error"
            log(project_name, f"Task failed: {error_msg[:100]}", "❌")

            if new_attempts >= manifest.max_task_attempts:
                update_task_status(
                    manifest, task.id, "failed",
                    error=error_msg, attempts=new_attempts,
                )
                log(project_name,
                    f"Task \"{task.title}\" exceeded {manifest.max_task_attempts} attempts — marking failed",
                    "🛑")
            else:
                update_task_status(
                    manifest, task.id, "pending",
                    error=error_msg, attempts=new_attempts,
                )
                log(project_name,
                    f"Will retry ({new_attempts}/{manifest.max_task_attempts})",
                    "🔄")

            manifest = load_manifest(project_path) or manifest
