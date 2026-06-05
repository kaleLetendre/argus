"""Call Claude through the Claude Agent SDK, reusing the local CLI auth.

This drives the ``claude`` CLI already installed and logged in on the server.
The call is locked down to *pure reasoning*: no tools, no project/user settings
bleed-in (so it won't pick up this repo's CLAUDE.md), a single turn.

HARD RULE: Argus must NEVER spend pay-per-use Anthropic API credits. The cost
cap is the subscription the user has already paid for. We enforce this by
stripping ``ANTHROPIC_API_KEY``/``ANTHROPIC_AUTH_TOKEN`` from the environment
the SDK subprocess inherits, so it can *only* authenticate via the logged-in
``claude`` CLI subscription session. If a key leaks into the env it is ignored;
if the CLI is not logged in, the call fails rather than falling back to credits.
Do not add an API-key fallback or a dual-mode toggle here.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

# "opus" resolves to the strongest current Opus via the CLI. Override per call.
DEFAULT_MODEL = "opus"

# Anything that could route the CLI to metered/pay-per-use billing instead of
# the subscription session. All stripped before every call. This is a denylist
# of the known billing-routing toggles (key auth, and the Bedrock/Vertex/base-URL
# gateways), so a box configured for any of those still can't bill.
_PAID_CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)


@contextlib.contextmanager
def _subscription_only_env():
    """Remove pay-per-use credentials for the duration of an SDK call.

    The SDK spawns the ``claude`` CLI as a subprocess that inherits ``os.environ``
    at spawn time; with these vars absent it can only use the stored subscription
    login. Restored afterwards so the rest of the process is untouched.
    """
    saved = {k: os.environ.pop(k) for k in _PAID_CREDENTIAL_VARS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


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
    """Synchronous one-shot: send prompt, return Claude's final text.

    Always runs under :func:`_subscription_only_env`, so it can never bill API
    credits (subscription session only).
    """
    with _subscription_only_env():
        return asyncio.run(_run(prompt, system, model))
