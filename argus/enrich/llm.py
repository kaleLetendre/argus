"""Call Claude through the Claude Agent SDK, reusing the local CLI auth.

This drives the ``claude`` CLI already installed and logged in on the server, so
no separate ANTHROPIC_API_KEY is required (it falls back to the subscription
session when the key is unset). The call is locked down to *pure reasoning*: no
tools, no project/user settings bleed-in (so it won't pick up this repo's
CLAUDE.md), a single turn.
"""

from __future__ import annotations

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

# "opus" resolves to the strongest current Opus via the CLI. Override per call.
DEFAULT_MODEL = "opus"


async def _run(prompt: str, system: str, model: str) -> str:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        allowed_tools=[],          # pure text generation, no file/tool access
        permission_mode="bypassPermissions",
        setting_sources=[],        # don't load ~/.claude or repo .claude settings
        max_turns=1,               # one-shot, no agentic looping
    )
    result = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message.result or ""
    return result


def ruminate(prompt: str, system: str, model: str = DEFAULT_MODEL) -> str:
    """Synchronous one-shot: send prompt, return Claude's final text."""
    return asyncio.run(_run(prompt, system, model))
