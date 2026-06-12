"""Conversational orchestrator."""

from __future__ import annotations

from argus.contracts.models import Utterance, Reply
from argus.agents.llm import ruminate
from argus.config import llm_config

def submit(utterance: Utterance) -> Reply:
    try:
        config = llm_config()
        text = ruminate(utterance.text, config.system_prompt)
        return Reply(text, "answer")
    except Exception as exc:
        return Reply(f"Error: {exc}", "error", found=False)
