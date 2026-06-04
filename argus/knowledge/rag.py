"""Retrieval over a workspace's markdown docs.

NOTE: This is a deliberate placeholder. It scores doc paragraphs by keyword
overlap so the end-to-end flow works today without committing to an embedding
stack. The interface (``retrieve`` returning ranked ``Passage`` objects) is what
the rest of the system depends on, so swapping in real embeddings later is a
drop-in change.

TODO(embeddings): replace ``_score`` with vector similarity once we pick a
backend (local sentence-transformers vs. a hosted embedding API). Keep
``retrieve``'s signature stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from argus.workspace.models import Workspace


@dataclass
class Passage:
    """A retrieved chunk of prose plus where it came from."""

    text: str
    source: Path
    score: float


def _chunks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    # Split on blank lines into paragraph-ish chunks.
    return [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(query_tokens: set[str], chunk: str) -> float:
    chunk_tokens = _tokens(chunk)
    if not chunk_tokens or not query_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def retrieve(workspace: Workspace, query: str, top_k: int = 3) -> list[Passage]:
    """Return the ``top_k`` most relevant doc passages for ``query``."""
    query_tokens = _tokens(query)
    scored: list[Passage] = []
    for doc_path in workspace.doc_paths:
        for chunk in _chunks(doc_path):
            score = _score(query_tokens, chunk)
            if score > 0:
                scored.append(Passage(text=chunk, source=doc_path, score=score))
    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:top_k]
