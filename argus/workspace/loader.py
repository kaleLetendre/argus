"""Load a workspace folder from disk into the in-memory model.

Expected layout of a project folder::

    workspaces/<slug>/
        workspace.yaml   # identity: name, aliases, description
        graph.yaml       # entities (with facts) and edges
        docs/*.md        # prose knowledge for the RAG layer

Both YAML files are optional in the sense that a half-built workspace still
loads; missing pieces just produce an empty graph or no docs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from argus.workspace.models import Edge, Entity, Fact, Graph, Workspace


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _parse_entity(raw: dict) -> Entity:
    facts = {
        key: Fact.parse(key, value)
        for key, value in (raw.get("facts") or {}).items()
    }
    return Entity(
        id=raw["id"],
        type=raw.get("type", "thing"),
        name=raw.get("name", raw["id"]),
        aliases=list(raw.get("aliases") or []),
        facts=facts,
        docs=list(raw.get("docs") or []),
    )


def _parse_graph(data: dict) -> Graph:
    entities = {}
    for raw in data.get("entities") or []:
        entity = _parse_entity(raw)
        entities[entity.id] = entity
    edges = [Edge.parse(raw) for raw in data.get("edges") or []]
    return Graph(entities=entities, edges=edges)


def load_workspace(path: Path | str) -> Workspace:
    """Read a single project folder into a :class:`Workspace`."""
    path = Path(path)
    meta = _load_yaml(path / "workspace.yaml")
    graph = _parse_graph(_load_yaml(path / "graph.yaml"))

    docs_dir = path / "docs"
    doc_paths = sorted(docs_dir.glob("*.md")) if docs_dir.is_dir() else []

    return Workspace(
        slug=meta.get("slug", path.name),
        name=meta.get("name", path.name),
        path=path,
        aliases=list(meta.get("aliases") or []),
        description=meta.get("description", ""),
        graph=graph,
        doc_paths=doc_paths,
    )
