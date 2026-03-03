"""Agent execution via Claude Code SDK."""

from pathlib import Path

from .models import AgentConfig, AgentResult


async def run_agent(
    agent_config: AgentConfig,
    cwd: Path,
    prompt: str,
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

    output_parts: list[str] = []
    total_cost = 0.0

    try:
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        output_parts.append(block.text)

            if hasattr(message, "cost_usd"):
                total_cost = message.cost_usd or 0.0

        return AgentResult(
            success=True,
            output="\n".join(output_parts),
            cost_usd=total_cost,
        )

    except Exception as e:
        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            error=str(e),
        )
