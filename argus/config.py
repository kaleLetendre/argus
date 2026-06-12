"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    system_prompt: str = ""


def llm_config() -> LLMConfig:
    _load_dotenv()
    return LLMConfig(
        provider=os.environ.get("ARGUS_LLM_PROVIDER", "claude").lower(),
        model=os.environ.get("ARGUS_LLM_MODEL", "opus"),
        system_prompt=os.environ.get("ARGUS_SYSTEM_PROMPT", ""),
    )

