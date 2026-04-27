"""Thin Claude Agent SDK wrapper. Per design §8, §12.5, §12.6, §12.8."""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from autopilot.config import AutopilotConfig
from autopilot.domain.errors import BudgetExceeded
from autopilot.domain.ids import RunId
from autopilot.domain.parse import _split_frontmatter
from autopilot.log import emit

_ROLES_DIR = Path(__file__).parent / "roles"
_FAKE_AGENT_ENV = "AUTOPILOT_FAKE_AGENT"
_FAKE_DELAY_ENV = "AUTOPILOT_FAKE_DELAY_MS"


@dataclass
class AgentResult:
    success: bool
    output: str
    error: str | None = None
    cost_usd: float = 0.0
    summary: str | None = None


@dataclass
class RoleConfig:
    """Parsed role configuration from `roles/{role}.md`."""

    name: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    max_turns: int = 50
    max_budget_usd: float | None = None
    model: str | None = None


def _load_role(role: str) -> RoleConfig:
    """Load a role config from `src/autopilot/agents/roles/{role}.md`."""
    path = _ROLES_DIR / f"{role}.md"
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text, path)

    # Prefer explicit frontmatter system_prompt; otherwise use the body text.
    system_prompt = fm.get("system_prompt")
    if not system_prompt:
        system_prompt = body

    allowed_tools_raw = fm.get("allowed_tools") or []
    if not isinstance(allowed_tools_raw, list):
        allowed_tools_raw = []

    max_budget = fm.get("max_budget_usd")
    max_budget_f = float(max_budget) if max_budget is not None else None

    max_turns_raw = fm.get("max_turns", 50)
    try:
        max_turns = int(max_turns_raw)
    except (TypeError, ValueError):
        max_turns = 50

    return RoleConfig(
        name=str(fm.get("name") or role),
        system_prompt=system_prompt,
        allowed_tools=[str(t) for t in allowed_tools_raw],
        permission_mode=str(fm.get("permission_mode") or "default"),
        max_turns=max_turns,
        max_budget_usd=max_budget_f,
        model=fm.get("model"),
    )


def _extract_summary(output: str) -> str | None:
    """Extract a summary block if the role convention emits one.

    Convention: worker/evaluator-style roles may emit `SUMMARY: <text>` on a line,
    or a `## Summary` / `## SUMMARY` markdown section. Returns None if no match.
    """
    m = re.search(r"^SUMMARY:\s*(.+?)$", output, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"^##\s+summary\s*\n+(.+?)(?=\n##\s|\Z)",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return None


async def run_agent(
    role: str,
    prompt: str,
    cfg: AutopilotConfig,
    *,
    cwd: Path | None = None,
    run_id: RunId | None = None,
) -> AgentResult:
    """Invoke a role via the Claude Agent SDK. See design §8.

    Test seams (§12.8):
      - `AUTOPILOT_FAKE_AGENT`: when set, bypass the SDK and return canned output.
        If the value points to a **directory**, read `<dir>/<role>.txt` for each call
        (missing file → `AgentResult(success=False, error=...)`).
        If the value points to a **file**, use the same file for every role (legacy).
      - `AUTOPILOT_FAKE_DELAY_MS`: only honoured when `AUTOPILOT_FAKE_AGENT` is set;
        inserts an `asyncio.sleep` before returning, giving fault tests a
        deterministic window to inject a kill.
    """
    cwd = cwd if cwd is not None else Path.cwd()
    role_cfg = _load_role(role)

    emit(
        "agent.call.start",
        role=role,
        run_id=run_id,
        cwd=str(cwd),
    )
    start = time.monotonic()

    # Test seam §12.8: AUTOPILOT_FAKE_AGENT bypasses the SDK entirely.
    fake = os.environ.get(_FAKE_AGENT_ENV)
    if fake:
        fake_path = Path(fake)
        if fake_path.is_dir():
            role_file = fake_path / f"{role}.txt"
            if not role_file.is_file():
                duration_ms = int((time.monotonic() - start) * 1000)
                emit(
                    "agent.call.end",
                    role=role,
                    run_id=run_id,
                    cost_usd=0.0,
                    duration_ms=duration_ms,
                    status="error",
                    **{"error.type": "FakeAgentMissing", "error.message": str(role_file)},
                )
                return AgentResult(
                    success=False,
                    output="",
                    error=f"no fake output for role {role}",
                )
            output = role_file.read_text(encoding="utf-8")
        else:
            output = fake_path.read_text(encoding="utf-8")

        delay_raw = os.environ.get(_FAKE_DELAY_ENV)
        if delay_raw:
            try:
                delay_ms = int(delay_raw)
            except ValueError:
                delay_ms = 0
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

        duration_ms = int((time.monotonic() - start) * 1000)
        emit(
            "agent.call.end",
            role=role,
            run_id=run_id,
            cost_usd=0.0,
            duration_ms=duration_ms,
            status="ok",
        )
        return AgentResult(
            success=True,
            output=output,
            cost_usd=0.0,
            summary=_extract_summary(output),
        )

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        emit(
            "agent.call.end",
            role=role,
            run_id=run_id,
            cost_usd=0.0,
            duration_ms=duration_ms,
            status="error",
            **{"error.type": "ImportError", "error.message": str(e)},
        )
        return AgentResult(
            success=False,
            output="",
            error=(
                "claude-agent-sdk not installed. "
                "Install it or set AUTOPILOT_FAKE_AGENT for deterministic runs."
            ),
        )

    options = ClaudeAgentOptions(
        system_prompt=role_cfg.system_prompt or None,
        allowed_tools=role_cfg.allowed_tools,
        cwd=str(cwd),
    )
    if role_cfg.permission_mode and role_cfg.permission_mode != "default":
        options.permission_mode = role_cfg.permission_mode
    if role_cfg.max_turns:
        options.max_turns = role_cfg.max_turns
    if role_cfg.max_budget_usd:
        options.max_budget_usd = role_cfg.max_budget_usd
    if role_cfg.model:
        options.model = role_cfg.model
    # Session naming TODO preserved — SDK doesn't currently expose a knob.
    options.setting_sources = ["project"]

    output_parts: list[str] = []
    total_cost = 0.0

    async def _drain() -> None:
        nonlocal total_cost
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        output_parts.append(block.text)
            if hasattr(message, "total_cost_usd") and message.total_cost_usd is not None:
                total_cost = message.total_cost_usd

    try:
        await asyncio.wait_for(_drain(), timeout=cfg.agent_call_timeout_sec)
    except TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        emit(
            "agent.call.end",
            role=role,
            run_id=run_id,
            cost_usd=total_cost,
            duration_ms=duration_ms,
            status="error",
            **{"error.type": "TimeoutError", "error.message": "agent call timed out"},
        )
        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            cost_usd=total_cost,
            error="agent call timed out",
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        emit(
            "agent.call.end",
            role=role,
            run_id=run_id,
            cost_usd=total_cost,
            duration_ms=duration_ms,
            status="error",
            **{"error.type": type(e).__name__, "error.message": str(e)},
        )
        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            cost_usd=total_cost,
            error=str(e),
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    output = "\n".join(output_parts)

    # Budget contract §12.6: per-call ceiling enforced here.
    if total_cost > cfg.max_cost_per_call_usd:
        emit(
            "agent.call.end",
            role=role,
            run_id=run_id,
            cost_usd=total_cost,
            duration_ms=duration_ms,
            status="error",
            **{"error.type": "BudgetExceeded"},
        )
        raise BudgetExceeded(
            scope="per_call",
            limit_usd=cfg.max_cost_per_call_usd,
            actual_usd=total_cost,
        )

    emit(
        "agent.call.end",
        role=role,
        run_id=run_id,
        cost_usd=total_cost,
        duration_ms=duration_ms,
        status="ok",
    )
    return AgentResult(
        success=True,
        output=output,
        cost_usd=total_cost,
        summary=_extract_summary(output),
    )
