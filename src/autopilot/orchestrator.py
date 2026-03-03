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
from .prompts import build_judge_prompt, build_worker_prompt, parse_judge_result


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

    # --- Step 1: Check approval / run judge ---

    if not manifest.approved:
        log(project_name, "Not approved — running readiness evaluation...", "🔍")

        try:
            judge_config = load_agent_config("judge", agents_dir)
        except FileNotFoundError:
            log(project_name, "No judge agent config found — skipping", "❌")
            return

        judge_prompt = build_judge_prompt(manifest)
        result = await run_agent(judge_config, project_path, judge_prompt)

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

                update_manifest_frontmatter(manifest, {"status": "paused"})
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
        result = await run_agent(worker_config, project_path, worker_prompt)

        if result.cost_usd > 0:
            log(project_name, f"Task cost: ${result.cost_usd:.4f}", "💰")

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
                    task.attempts += 1
                    update_task_status(manifest, task.id, "pending",
                                      "Worker completed without marking task done")
                    manifest = load_manifest(project_path) or manifest
            else:
                log(project_name, "Could not reload manifest after task", "❌")
                break
        else:
            error_msg = result.error or "Unknown error"
            log(project_name, f"Task failed: {error_msg[:100]}", "❌")

            task.attempts += 1
            if task.attempts >= manifest.max_task_attempts:
                update_task_status(manifest, task.id, "failed", error_msg)
                log(project_name,
                    f"Task \"{task.title}\" exceeded {manifest.max_task_attempts} attempts — marking failed",
                    "🛑")
            else:
                update_task_status(manifest, task.id, "pending", error_msg)
                log(project_name,
                    f"Will retry ({task.attempts}/{manifest.max_task_attempts})",
                    "🔄")

            manifest = load_manifest(project_path) or manifest
