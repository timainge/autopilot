"""Agent execution via Claude Code SDK."""

import time
from pathlib import Path

from .log import log
from .models import AgentConfig, AgentResult

# Interval (seconds) between periodic elapsed/cost status lines
STATUS_INTERVAL = 30


async def run_agent(
    agent_config: AgentConfig,
    cwd: Path,
    prompt: str,
    project_name: str = "",
    role_name: str = "",
) -> AgentResult:
    """Execute an agent session using the Claude Code SDK's query()."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return AgentResult(
            success=False,
            error="claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
        )

    options = ClaudeAgentOptions(
        system_prompt=agent_config.system_prompt or None,
        allowed_tools=agent_config.allowed_tools,
        cwd=str(cwd),
    )

    # Session naming: makes sessions appear as "autopilot/{project}/{role}" in /resume history
    if role_name:
        options.extra_args = {"session-name": f"autopilot/{project_name or cwd.name}/{role_name}"}

    if agent_config.permission_mode and agent_config.permission_mode != "default":
        options.permission_mode = agent_config.permission_mode

    if agent_config.max_turns:
        options.max_turns = agent_config.max_turns

    if agent_config.max_budget_usd:
        options.max_budget_usd = agent_config.max_budget_usd

    if agent_config.model:
        options.model = agent_config.model

    # Pick up project-level .claude/ config if present
    options.setting_sources = ["project"]

    label = project_name or cwd.name
    output_parts: list[str] = []
    total_cost = 0.0
    start = time.monotonic()
    last_status = start

    try:
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        log(label, block.name, icon="~")
                    elif hasattr(block, "text"):
                        output_parts.append(block.text)

            if hasattr(message, "cost_usd"):
                total_cost = message.cost_usd or 0.0

            now = time.monotonic()
            if now - last_status >= STATUS_INTERVAL:
                elapsed = int(now - start)
                log(label, f"{elapsed}s elapsed, ${total_cost:.3f} spent", icon="T")
                last_status = now

        elapsed = int(time.monotonic() - start)
        log(label, f"done ({elapsed}s, ${total_cost:.3f})", icon="O")

        return AgentResult(
            success=True,
            output="\n".join(output_parts),
            cost_usd=total_cost,
        )

    except Exception as e:
        elapsed = int(time.monotonic() - start)
        log(label, f"failed after {elapsed}s, ${total_cost:.3f}: {e}", icon="X")

        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            error=str(e),
        )
