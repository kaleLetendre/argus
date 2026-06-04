"""Runtime configuration, read from the environment (and a local .env file).

Keeps connection details out of the code and out of git. ``.env`` is gitignored;
see ``.env.example`` for the shape.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACES_ROOT = REPO_ROOT / "workspaces"


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str


def neo4j_config() -> Neo4jConfig:
    _load_dotenv()
    return Neo4jConfig(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", ""),
    )
