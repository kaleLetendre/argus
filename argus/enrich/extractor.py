"""Ruminate over a workspace's docs and stage graph additions for review.

Flow: pull the existing graph + the prose docs, ask Claude what entities, facts,
and relationships the docs support that aren't in the graph yet, parse the JSON,
and stage each proposal (never auto-apply). Machine-extracted knowledge always
carries ``source: "claude-extraction:<doc>"`` and a capped confidence, so it is
never confused with what you stated yourself.

``enrich_workspace`` takes an injectable ``llm`` callable so the pipeline can be
tested with canned output, without spending credits or hitting the network.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from argus.enrich.llm import DEFAULT_MODEL, ruminate

SYSTEM = (
    "You are a careful knowledge-graph extractor for a mechanic's shop assistant. "
    "You read project documents and propose structured additions to a knowledge "
    "graph. Rules: only propose facts and relationships explicitly supported by the "
    "provided documents; never invent specifications or numbers; for every proposal "
    "include the exact supporting quote from the document; prefer precision over "
    "recall; if a value is uncertain or hedged in the text, give it a lower "
    "confidence. A wrong torque spec is dangerous, so when in doubt, leave it out."
)

# The shape we ask Claude to return. Kept in the prompt (robust) rather than
# relying on a provider-specific structured-output mode.
_SCHEMA_HINT = """Return ONLY a JSON object with this shape (no prose, no markdown fence):
{
  "entities": [
    {"id": "slug-id", "type": "engine|part|tool|...", "name": "Display Name",
     "aliases": ["..."], "evidence": "exact quote", "doc": "filename.md", "confidence": 0.0-1.0}
  ],
  "facts": [
    {"entity_id": "existing-or-new-id", "key": "snake_case_key", "value": <number or string>,
     "unit": "ft-lb" or null, "note": "..." or null, "evidence": "exact quote",
     "doc": "filename.md", "confidence": 0.0-1.0}
  ],
  "relationships": [
    {"source": "entity-id", "relation": "installed_on|part_of|...", "target": "entity-id",
     "weight": 0.0-1.0, "confidence": 0.0-1.0, "evidence": "exact quote", "doc": "filename.md"}
  ]
}
Only include items NOT already present in the existing graph below."""

# Machine-extracted knowledge is never certain and never below this floor.
_CONF_CAP = 0.9
_CONF_FLOOR = 0.1


def _clamp(value, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(_CONF_FLOOR, min(_CONF_CAP, v))


def build_prompt(snapshot: str, docs: list[dict]) -> str:
    doc_blocks = "\n\n".join(f"### {d['name']}\n{d['text']}" for d in docs)
    return (
        f"{_SCHEMA_HINT}\n\n"
        f"## Existing graph (do not duplicate)\n{snapshot or '(empty)'}\n\n"
        f"## Project documents\n{doc_blocks}\n"
    )


def parse_proposals(raw: str) -> list[dict]:
    """Pull the JSON object out of Claude's reply and flatten to proposals."""
    data = _extract_json(raw)
    if not data:
        return []
    proposals: list[dict] = []

    for e in data.get("entities") or []:
        if not e.get("id") or not e.get("name"):
            continue
        proposals.append(
            {
                "kind": "entity",
                "id": e["id"],
                "type": e.get("type", "thing"),
                "name": e["name"],
                "aliases": e.get("aliases") or [],
                "evidence": e.get("evidence", ""),
                "doc": e.get("doc", ""),
                "confidence": _clamp(e.get("confidence")),
            }
        )
    for f in data.get("facts") or []:
        if not f.get("entity_id") or not f.get("key"):
            continue
        proposals.append(
            {
                "kind": "fact",
                "entity_id": f["entity_id"],
                "key": f["key"],
                "value": f.get("value"),
                "unit": f.get("unit"),
                "note": f.get("note"),
                "evidence": f.get("evidence", ""),
                "doc": f.get("doc", ""),
                "confidence": _clamp(f.get("confidence")),
            }
        )
    for r in data.get("relationships") or []:
        if not r.get("source") or not r.get("target") or not r.get("relation"):
            continue
        proposals.append(
            {
                "kind": "relationship",
                "source": r["source"],
                "relation": r["relation"],
                "target": r["target"],
                "weight": _clamp(r.get("weight"), 1.0),
                "confidence": _clamp(r.get("confidence")),
                "evidence": r.get("evidence", ""),
                "doc": r.get("doc", ""),
            }
        )
    return proposals


def _extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    # Strip a ```json ... ``` fence if present.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # Otherwise take the outermost { ... }.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def enrich_workspace(
    slug: str,
    store,
    llm: Callable[[str, str, str], str] = ruminate,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Run extraction for one workspace; returns a summary of what was staged."""
    docs = store.get_docs(slug)
    if not docs:
        return {"staged": 0, "reason": "no docs in this context"}
    snapshot = store.graph_snapshot(slug)
    raw = llm(build_prompt(snapshot, docs), SYSTEM, model)
    proposals = parse_proposals(raw)
    ids = store.stage_proposals(slug, proposals)
    return {"staged": len(ids), "ids": ids, "proposals": proposals}
